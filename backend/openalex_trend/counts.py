"""集計用の基本取得: 年別件数(group_by)、総件数、cursor ページング。"""

from __future__ import annotations

from typing import Iterator

import pandas as pd

from .client import OpenAlexClient
from .config import Config
from .queries import LEVELS, denominator_params


def yearly_counts(client: OpenAlexClient, params: dict) -> pd.Series:
    """group_by=publication_year の結果を 年 -> 件数 の Series にする。"""
    data = client.get(params)
    s = pd.Series(
        {int(g["key"]): int(g["count"]) for g in data["group_by"]}, dtype="int64"
    )
    return s.sort_index()


def total_count(client: OpenAlexClient, params: dict) -> int:
    """meta.count(条件に一致した総件数)を返す。"""
    return int(client.get(params)["meta"]["count"])


def iter_works(client: OpenAlexClient, params: dict) -> Iterator[dict]:
    """cursor ページングで全件を順に返す。next_cursor が尽きたら終了。"""
    params = dict(params)
    while True:
        data = client.get(params)
        results = data.get("results", [])
        yield from results
        cursor = data.get("meta", {}).get("next_cursor")
        if not results or not cursor:
            return
        params["cursor"] = cursor


def fetch_denominators(client: OpenAlexClient, cfg: Config) -> dict[str, pd.Series]:
    """出現率の分母(all / field / subfield)の年別論文数。各1リクエスト。"""
    return {lv: yearly_counts(client, denominator_params(cfg, lv)) for lv in LEVELS}
