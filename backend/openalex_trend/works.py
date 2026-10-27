"""語句ごとの論文取得。取得結果(各ページ)はクライアントのキャッシュに残る。

トピックの追加・語句の追加のとき、すでに取得した語句は再検索されない。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .client import OpenAlexClient
from .config import Config, Field
from .counts import iter_works, total_count
from .queries import (
    LEVELS,
    PAGE_SIZE,
    count_params,
    denominator_params,
    quote,
    unique_phrases,
    works_params,
)


@dataclass(frozen=True)
class Work:
    id: str
    title: str
    year: int
    cited_by_count: int
    cites_by_year: dict[int, int] = field(default_factory=dict)  # 引用された年 -> 被引用数
    fwci: float | None = None
    top10: bool | None = None  # 被引用上位10%か(同分野・同年・同種別の比較)
    field_id: str = ""
    subfield_id: str = ""
    topic_name: str = ""


def short_id(url: str | None) -> str:
    """https://openalex.org/subfields/2613 -> subfields/2613"""
    return (url or "").split("openalex.org/")[-1]


def parse_work(w: dict) -> Work:
    topic = w.get("primary_topic") or {}
    pct = w.get("citation_normalized_percentile") or {}
    top10 = pct.get("is_in_top_10_percent")
    return Work(
        id=w["id"],
        title=w.get("title") or "",
        year=int(w["publication_year"]),
        cited_by_count=int(w.get("cited_by_count") or 0),
        cites_by_year={
            int(c["year"]): int(c["cited_by_count"]) for c in w.get("counts_by_year") or []
        },
        fwci=None if w.get("fwci") is None else float(w["fwci"]),
        top10=None if top10 is None else bool(top10),
        field_id=short_id((topic.get("field") or {}).get("id")),
        subfield_id=short_id((topic.get("subfield") or {}).get("id")),
        topic_name=topic.get("display_name") or "",
    )


def works_params_cached(client: OpenAlexClient, cfg: Config, phrase: str) -> bool:
    """その語句の最初のページがキャッシュ済みか(取得済みの目安)。"""
    return client.is_cached(works_params(cfg, phrase))


def fetch_phrase_works(client: OpenAlexClient, cfg: Config, phrase: str) -> dict[str, Work]:
    return {w["id"]: parse_work(w) for w in iter_works(client, works_params(cfg, phrase))}


def fetch_topic_works(
    client: OpenAlexClient, cfg: Config, f: Field
) -> tuple[dict[str, Work], dict[str, int]]:
    """トピックの全論文(語句ごとの結果を work ID で和集合)と、語句ごとの件数。"""
    merged: dict[str, Work] = {}
    per_phrase: dict[str, int] = {}
    for phrase in unique_phrases(f.phrases):
        works = fetch_phrase_works(client, cfg, phrase)
        per_phrase[phrase] = len(works)
        merged.update(works)
    return merged, per_phrase


def plan_requests(client: OpenAlexClient, cfg: Config) -> tuple[list[dict], int]:
    """実行前に見積もる。(確定しているリクエスト一覧, カーソルページ数の見積り)。

    語句ごとの件数を先に取り(各1リクエスト)、ページ数 = 件数/200 で見積もる。
    取得済み(キャッシュあり)の語句はページ取得が新規にならないので見積りに入れない。
    """
    reqs = [denominator_params(cfg, lv) for lv in LEVELS]
    pages = 0
    for f in cfg.fields:
        for phrase in unique_phrases(f.phrases):
            if works_params_cached(client, cfg, phrase):
                continue
            p = count_params(cfg, quote(phrase))
            reqs.append(p)
            pages += math.ceil(total_count(client, p) / PAGE_SIZE)
    return reqs, pages
