"""PC版ダッシュボードのローカルサーバー。

画面(frontend/)を配信し、トピックの編集を受け付けて再集計する。
- 自分のPC(127.0.0.1)だけで待ち受ける。APIキーはこのプロセスの環境変数にだけ置く
- 語句ごとの取得結果はメモリとディスク(data/cache)に残すので、除外語句の変更や
  取得済みの語句は通信なしで即座に再集計できる。新しい語句の分だけ OpenAlex に問い合わせる
- 編集は「取得と集計がすべて成功したら topics.json に保存」する(失敗したら元のまま)
"""

from __future__ import annotations

import json
import math
import threading
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .client import OpenAlexClient, OpenAlexError
from .config import REPO_ROOT, Config, fields_from_topics, topics_from_fields
from .counts import total_count
from .pipeline import build
from .queries import PAGE_SIZE, count_params, quote, unique_phrases
from .report import write_dashboard_json
from .text import normalize_phrase
from .topics import TopicError, save_topics, validate_topics
from .works import Work, fetch_phrase_works, works_params_cached

STATIC_ROOT = REPO_ROOT / "frontend"
MAX_BODY = 64 * 1024
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".css": "text/css; charset=utf-8",
}


class DashboardApp:
    """取得・集計の状態を持つ。取得は同時に1つだけ(別スレッド)で行う。"""

    def __init__(self, cfg: Config, client: OpenAlexClient) -> None:
        self.cfg = cfg
        self.client = client
        self.topics = topics_from_fields(cfg.fields)
        self.doc: dict | None = None
        self.memo: dict[str, dict[str, Work]] = {}  # 正規化した語句 -> 論文
        self.job = {"state": "idle", "message": "", "done": 0, "total": 0}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # 取得済みの語句はメモリから返す(ディスクのキャッシュより速い)
    def _fetch_phrase(self, client: OpenAlexClient, cfg: Config, phrase: str) -> dict[str, Work]:
        key = normalize_phrase(phrase)
        if key not in self.memo:
            self.memo[key] = fetch_phrase_works(client, cfg, phrase)
        return self.memo[key]

    def busy(self) -> bool:
        return self.job["state"] == "running"

    def start(self, topics: list[dict] | None = None, wait: bool = False) -> bool:
        """再集計を始める。topics を渡すと、成功時に topics.json へ保存する。実行中なら False。"""
        with self._lock:
            if self.busy():
                return False
            self.job = {"state": "running", "message": "準備中", "done": 0, "total": 0}
            self._thread = threading.Thread(target=self._run, args=(topics,), daemon=True)
            self._thread.start()
        if wait:
            self._thread.join()
        return True

    def _run(self, topics: list[dict] | None) -> None:
        base = self.client.network_requests
        progress = lambda: self.job.update(done=self.client.network_requests - base)  # noqa: E731
        try:
            cfg = replace(self.cfg, fields=fields_from_topics(topics)) if topics else self.cfg
            # 見積り: 未取得の語句だけ件数を確認し、ページ数(件数/200)を出す
            self.job["message"] = "件数を確認中"
            pages = checks = 0
            for f in cfg.fields:
                for p in unique_phrases(f.phrases):
                    if normalize_phrase(p) in self.memo or works_params_cached(self.client, cfg, p):
                        continue
                    checks += 1
                    pages += math.ceil(total_count(self.client, count_params(cfg, quote(p))) / PAGE_SIZE)
                    progress()
            self.job.update(total=checks + pages, message="論文を取得中" if pages else "集計中")

            def fetch(client, c, phrase):
                works = self._fetch_phrase(client, c, phrase)
                progress()
                return works

            result = build(self.client, cfg, fetch)
            if topics is not None:
                save_topics(cfg.topics_path, topics)
                self.cfg, self.topics = cfg, topics
            self.doc = result.doc
            write_dashboard_json(result.doc, cfg.output_dir)
            progress()
            self.job.update(state="done", message="完了")
        except (OpenAlexError, TopicError) as e:
            self.job.update(state="error", message=str(e))
        except Exception as e:  # 想定外でもサーバーは落とさず、画面に出す
            self.job.update(state="error", message=f"内部エラー: {type(e).__name__}: {e}")


def make_handler(app: DashboardApp, static_root: Path = STATIC_ROOT, port: int = 8765):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # アクセスログは出さない
            pass

        # ---- 応答 ----
        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), CONTENT_TYPES[".json"])

        def _host_ok(self) -> bool:
            # 他のサイトからの書き込み(DNS rebinding / CSRF)を防ぐ
            if self.headers.get("Host") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or urlparse(origin).netloc in allowed_hosts

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (static_root / rel).resolve()
            if not target.is_relative_to(static_root.resolve()) or not target.is_file():
                return self._json(404, {"error": "not found"})
            ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), ctype)

        # ---- ルーティング ----
        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            path = urlparse(self.path).path
            if path == "/api/state":
                return self._json(200, {"editable": True, "job": app.job, "has_data": app.doc is not None})
            if path == "/api/topics":
                return self._json(200, {"topics": app.topics})
            if path in ("/api/dashboard", "/data/dashboard.json"):
                if app.doc is None:
                    return self._json(503, {"error": "集計中", "job": app.job})
                return self._json(200, app.doc)
            return self._static(path)

        def _read_json(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise TopicError("送信データが大きすぎる")
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise TopicError("JSON で送信すること")
            return json.loads(self.rfile.read(n) or b"null")

        def do_PUT(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            if urlparse(self.path).path != "/api/topics":
                return self._json(404, {"error": "not found"})
            try:
                topics = validate_topics((self._read_json() or {}).get("topics"))
            except (TopicError, ValueError, AttributeError) as e:
                return self._json(400, {"error": str(e) or "形式が不正"})
            if not app.start(topics):
                return self._json(409, {"error": "取得中のため、終わってから保存してください"})
            return self._json(202, {"job": app.job})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            if urlparse(self.path).path != "/api/refresh":
                return self._json(404, {"error": "not found"})
            if not app.start():
                return self._json(409, {"error": "取得中"})
            return self._json(202, {"job": app.job})

    return Handler


def serve(cfg: Config, client: OpenAlexClient, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = False) -> None:
    app = DashboardApp(cfg, client)
    httpd = ThreadingHTTPServer((host, port), make_handler(app, port=port))
    app.start()  # 起動時に集計(初回は全トピックを取得するので時間がかかる)
    url = f"http://127.0.0.1:{port}/"
    print(f"ダッシュボード: {url}  (止めるときはこの画面で Ctrl+C)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
