"""年別件数の取得(or方式 / union方式)。"""

from __future__ import annotations

import math
from typing import Iterator

import pandas as pd

from .client import OpenAlexClient
from .config import Config, Field
from .queries import (
    PAGE_SIZE,
    count_params,
    denominator_params,
    id_pages_params,
    numerator_params,
    quote,
)


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


def collect_work_years(client: OpenAlexClient, params: dict) -> dict[str, int]:
    """work ID -> 出版年 の辞書(同じ ID は1件に畳む)。"""
    return {w["id"]: int(w["publication_year"]) for w in iter_works(client, params)}


def union_work_years(
    client: OpenAlexClient, cfg: Config, field: Field
) -> dict[str, int]:
    """語句ごとに取得し、work ID で和集合を取る(OR条件が効かない場合の代替)。"""
    merged: dict[str, int] = {}
    for phrase in field.phrases:
        merged.update(collect_work_years(client, id_pages_params(cfg, quote(phrase))))
    return merged


def union_yearly_counts(
    client: OpenAlexClient, cfg: Config, field: Field
) -> pd.Series:
    years = union_work_years(client, cfg, field)
    return pd.Series(years).value_counts().sort_index().astype("int64")


def plan_requests(client: OpenAlexClient, cfg: Config) -> tuple[list[dict], int]:
    """実行前に見積もる。(確定しているリクエスト一覧, カーソルページ数の見積り)。

    union方式は語句ごとの件数を先に取り(各1リクエスト)、ページ数 = 件数/200 で見積もる。
    """
    reqs = [denominator_params(cfg)]
    if cfg.query_mode == "or":
        reqs += [numerator_params(cfg, f) for f in cfg.fields]
        return reqs, 0
    pages = 0
    for f in cfg.fields:
        for phrase in f.phrases:
            p = count_params(cfg, quote(phrase))
            reqs.append(p)
            pages += math.ceil(total_count(client, p) / PAGE_SIZE)
    return reqs, pages


def fetch_all(client: OpenAlexClient, cfg: Config) -> tuple[pd.Series, dict[str, pd.Series]]:
    """分母と各分野の分子(年別件数)を取得する。"""
    denominator = yearly_counts(client, denominator_params(cfg))
    counts: dict[str, pd.Series] = {}
    for f in cfg.fields:
        if cfg.query_mode == "or":
            counts[f.label] = yearly_counts(client, numerator_params(cfg, f))
        else:
            counts[f.label] = union_yearly_counts(client, cfg, f)
    return denominator, counts
