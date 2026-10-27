"""OpenAlex へ渡すクエリパラメータの組み立て(通信はしない)。"""

from __future__ import annotations

from .config import Config, Field

PAGE_SIZE = 200  # OpenAlex の per_page 上限


def quote(phrase: str) -> str:
    """フレーズ指定のため二重引用符で囲む。"""
    return '"' + phrase.replace('"', "").strip() + '"'


def or_query(phrases) -> str:
    """同義語・表記揺れを OR 条件でまとめた検索式。"""
    return " OR ".join(quote(p) for p in phrases)


def base_filter(cfg: Config) -> str:
    """分母・分子で共通の母集団。

    1論文に最大3つの Topic が付くため、subfield は primary_topic 側で絞る
    (topics.subfield だと同じ論文が複数の subfield で重複計上される)。
    """
    return (
        f"primary_topic.subfield.id:{cfg.subfield_id},"
        f"publication_year:{cfg.year_from}-{cfg.year_to}"
    )


def denominator_params(cfg: Config) -> dict:
    """分母: 同一 subfield の年別論文数。group_by は1リクエストにつき1つ。"""
    return {
        "filter": base_filter(cfg),
        "group_by": "publication_year",
        "per_page": PAGE_SIZE,
    }


def numerator_params(cfg: Config, field: Field) -> dict:
    """分子(or方式): タイトルが語句のいずれかに一致した論文の年別件数。"""
    return {
        **denominator_params(cfg),
        cfg.search_param: or_query(field.phrases),
    }


def count_params(cfg: Config, query: str) -> dict:
    """検索式に一致する総件数だけを取る(meta.count を読む)。"""
    return {
        "filter": base_filter(cfg),
        cfg.search_param: query,
        "per_page": 1,
        "select": "id",
    }


def id_pages_params(cfg: Config, query: str) -> dict:
    """work ID と年の一覧をカーソルページングで取るための初回パラメータ。"""
    return {
        "filter": base_filter(cfg),
        cfg.search_param: query,
        "per_page": PAGE_SIZE,
        "select": "id,publication_year",
        "cursor": "*",
    }
