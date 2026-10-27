"""OpenAlex APIクライアント。

- APIキーは環境変数 OPENALEX_API_KEY から読む。キャッシュ・ログ・例外にキーを残さない
- 429/5xx は指数バックオフでリトライする(Retry-After があれば尊重)
- 毎秒のリクエスト数を上限内に保つ
- 応答は JSON でキャッシュし、再実行時に同じクエリを打たない
- 1日の予算(リクエスト数換算)を超えそうなら実行前に止める
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import requests

from .config import Config

API_KEY_ENV = "OPENALEX_API_KEY"
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF_BASE_SEC = 1.0
RETRY_AFTER_CAP_SEC = 60.0


class OpenAlexError(RuntimeError):
    """API呼び出しの失敗。メッセージにAPIキーは含めない。"""


class BudgetExceeded(OpenAlexError):
    """1日の予算(推定費用)を超えるため、リクエストを打たずに中止した。"""


@dataclass(frozen=True)
class PlanSummary:
    """実行前に表示する推定リクエスト数と推定費用。"""

    total: int
    cached: int
    to_run: int
    cost_usd: float
    budget_usd: float
    extra_unknown: int = 0

    def format(self) -> str:
        s = (
            f"推定リクエスト数: {self.total + self.extra_unknown} "
            f"(キャッシュ済 {self.cached} / 新規 {self.to_run + self.extra_unknown})"
            f" 推定費用: ${self.cost_usd:.4f} (1日の上限 ${self.budget_usd:.2f})"
        )
        if self.extra_unknown:
            s += f"\n  うち {self.extra_unknown} 件は事前に確定できない分の見積り(カーソルページは件数÷200、サンプル抽出は分野数)"
        return s


def cache_key(base_url: str, params: dict) -> str:
    """URLとパラメータからキャッシュキーを作る。api_key は含めない。"""
    clean = {k: str(v) for k, v in params.items() if k != "api_key"}
    blob = json.dumps([base_url, sorted(clean.items())], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class OpenAlexClient:
    def __init__(
        self,
        cfg: Config,
        api_key: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self.network_requests = 0
        self.cache_hits = 0
        self.max_requests = math.floor(
            cfg.daily_budget_usd / cfg.cost_per_request_usd + 1e-9
        )
        cfg.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- キャッシュ -----------------------------------------------------
    def _cache_path(self, params: dict) -> Path:
        return self.cfg.cache_dir / f"{cache_key(self.cfg.base_url, params)}.json"

    def is_cached(self, params: dict) -> bool:
        return self._cache_path(params).exists()

    def _read_cache(self, path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        except (OSError, ValueError, KeyError):
            return None  # 壊れたキャッシュは無視して取り直す

    def _write_cache(self, path: Path, params: dict, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        payload = {"params": params, "response": data}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)  # 書き込み途中の破損を避ける

    # ---- 実行計画 -------------------------------------------------------
    def describe_plan(
        self, params_list: Iterable[dict], extra_unknown: int = 0
    ) -> PlanSummary:
        """重複を除いたリクエスト数と、キャッシュ済みを除いた推定費用を返す。"""
        unique = {cache_key(self.cfg.base_url, p): p for p in params_list}
        cached = sum(1 for p in unique.values() if self.is_cached(p))
        to_run = len(unique) - cached
        cost = (to_run + extra_unknown) * self.cfg.cost_per_request_usd
        return PlanSummary(
            len(unique), cached, to_run, cost, self.cfg.daily_budget_usd, extra_unknown
        )

    # ---- 取得 -----------------------------------------------------------
    def get(self, params: dict) -> dict:
        params = {k: v for k, v in params.items() if k != "api_key"}
        path = self._cache_path(params)
        cached = self._read_cache(path)
        if cached is not None:
            self.cache_hits += 1
            return cached
        data = self._request(params)
        self._write_cache(path, params, data)
        return data

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def _throttle(self) -> None:
        """直前のリクエストから 1/rate 秒以上あける。"""
        min_gap = 1.0 / self.cfg.rate_limit_per_sec
        now = self._clock()
        if self._last_request_at is not None:
            wait = self._last_request_at + min_gap - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request_at = now

    def _check_budget(self) -> None:
        if self.network_requests + 1 > self.max_requests:
            raise BudgetExceeded(
                f"1日の予算 ${self.cfg.daily_budget_usd:.2f} "
                f"({self.max_requests} リクエスト)を超えるため中止した"
            )

    def _request(self, params: dict) -> dict:
        send = {**params, "api_key": self.api_key} if self.api_key else dict(params)
        reason = ""
        for attempt in range(self.cfg.max_retries + 1):
            self._check_budget()
            self._throttle()
            self.network_requests += 1  # 再試行も費用側に数える(安全側)
            retry_after = None
            try:
                resp = self.session.get(
                    self.cfg.base_url, params=send, timeout=self.cfg.timeout_sec
                )
            except requests.RequestException as e:
                reason = f"通信エラー: {self._redact(str(e))}"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        raise OpenAlexError("応答がJSONではない") from None
                reason = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUS:
                    body = self._redact(resp.text[:200])
                    raise OpenAlexError(f"{reason}: {body}")
                retry_after = resp.headers.get("Retry-After")
            if attempt < self.cfg.max_retries:
                self._sleep(self._backoff(attempt, retry_after))
        raise OpenAlexError(f"リトライ上限に達した ({reason})")

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        """指数バックオフ(1,2,4,...秒)。Retry-After が大きければそちらを採る。"""
        wait = BACKOFF_BASE_SEC * 2**attempt
        try:
            if retry_after is not None:
                wait = max(wait, min(float(retry_after), RETRY_AFTER_CAP_SEC))
        except ValueError:
            pass
        return wait
