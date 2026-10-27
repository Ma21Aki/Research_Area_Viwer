"""クエリ検証: search.title の OR 条件とフレーズ指定が意図どおり効いているか確かめる。

OR条件全体の件数 n_or と各語句単独の件数 n_i について、効いているなら次が成り立つ。
    max(n_i) <= n_or <= sum(n_i)     (ORは和集合なので)
    n_or < 分母の総数                 (検索が無視されていれば n_or == 分母になる)
フレーズ指定は、引用符あり件数 <= 引用符なし(単語のAND)件数 が成り立つはず。
成り立たない場合は union 方式(語句ごとに取得して work ID の和集合)へ切り替える。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .client import OpenAlexClient
from .config import Config, Field
from .counts import total_count, yearly_counts
from .queries import count_params, denominator_params, or_query, quote


@dataclass
class FieldValidation:
    label: str
    n_or: int
    n_phrase: dict[str, int]  # 引用符あり(フレーズ)
    n_words: dict[str, int]  # 引用符なし(単語のAND)
    denominator_total: int
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def planned_requests(cfg: Config) -> list[dict]:
    reqs = [denominator_params(cfg, "all")]
    for f in cfg.fields:
        reqs.append(count_params(cfg, or_query(f.phrases)))
        for p in f.phrases:
            reqs.append(count_params(cfg, quote(p)))
            reqs.append(count_params(cfg, p))
    return reqs


def check_field(
    n_or: int, n_phrase: dict[str, int], n_words: dict[str, int], denominator_total: int
) -> tuple[list[str], list[str]]:
    """件数の関係から (失敗, 警告) のメッセージを返す。通信しない純粋関数。"""
    fails: list[str] = []
    warns: list[str] = []
    hi = max(n_phrase.values())
    if denominator_total > 0 and n_or >= denominator_total:
        fails.append("OR件数が分母と同じ: 検索パラメータが無視されている可能性")
    if n_or < hi:
        fails.append(f"OR件数({n_or})が単独語句の最大({hi})より少ない: ORが効いていない")
    if n_or > sum(n_phrase.values()):
        fails.append("OR件数が単独語句の合計を超える: 論理が不整合")
    if len(n_phrase) > 1 and n_or == hi and sum(n_phrase.values()) > hi:
        warns.append("OR件数が最大語句と同じ: 他の語句が部分集合でなければORが効いていない")
    for p, q in n_phrase.items():
        w = n_words[p]
        if q > w:
            fails.append(f'"{p}": フレーズ件数({q})が単語AND件数({w})を超える')
        elif q == w and q > 0:
            warns.append(f'"{p}": 引用符の有無で件数が同じ: フレーズ指定が効いていない可能性')
    return fails, warns


def validate_field(
    client: OpenAlexClient, cfg: Config, f: Field, denominator_total: int
) -> FieldValidation:
    n_or = total_count(client, count_params(cfg, or_query(f.phrases)))
    n_phrase = {p: total_count(client, count_params(cfg, quote(p))) for p in f.phrases}
    n_words = {p: total_count(client, count_params(cfg, p)) for p in f.phrases}
    fails, warns = check_field(n_or, n_phrase, n_words, denominator_total)
    return FieldValidation(f.label, n_or, n_phrase, n_words, denominator_total, fails, warns)


def validate_all(client: OpenAlexClient, cfg: Config) -> list[FieldValidation]:
    denom_total = int(yearly_counts(client, denominator_params(cfg, "all")).sum())
    return [validate_field(client, cfg, f, denom_total) for f in cfg.fields]


def format_report(results: list[FieldValidation]) -> str:
    lines = []
    for r in results:
        lines.append(f"[{'OK' if r.ok else 'NG'}] {r.label}: OR={r.n_or} 分母計={r.denominator_total}")
        for p in r.n_phrase:
            lines.append(f"    {p!r}: フレーズ={r.n_phrase[p]} 単語AND={r.n_words[p]}")
        lines += [f"    失敗: {m}" for m in r.failures]
        lines += [f"    警告: {m}" for m in r.warnings]
    if all(r.ok for r in results):
        lines.append("判定: OR条件・フレーズ指定は意図どおり")
    else:
        lines.append("判定: OR条件またはフレーズ指定が効いていない。run は語句ごとの取得なので、失敗した語句(上の失敗・警告)を個別に確認すること")
    return "\n".join(lines)


def write_report(results: list[FieldValidation], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "validation.json"
    doc = {"ok": all(r.ok for r in results), "fields": [asdict(r) for r in results]}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
