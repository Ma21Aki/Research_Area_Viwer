"""OpenAlex へ渡すクエリパラメータの組み立て(通信はしない)。"""

from __future__ import annotations

from .config import Config
from .text import normalize_phrase

PAGE_SIZE = 200  # OpenAlex の per_page 上限
LEVELS = ("all", "field", "subfield")  # 出現率の分母の切替(広い順)

# 論文単位で取得する項目。集計はすべて手元で行う(分母の切替・被引用の指標のため)
WORK_SELECT = (
    "id,title,publication_year,cited_by_count,counts_by_year,fwci,"
    "citation_normalized_percentile,primary_topic"
)


def quote(phrase: str) -> str:
    """フレーズ指定のため二重引用符で囲む。"""
    return '"' + phrase.replace('"', "").strip() + '"'


def or_query(phrases) -> str:
    """同義語・表記揺れを OR 条件でまとめた検索式。"""
    return " OR ".join(quote(p) for p in phrases)


def unique_phrases(phrases) -> list[str]:
    """正規化して重複する語句を除く(先に書かれた方を残す)。"""
    seen: dict[str, str] = {}
    for p in phrases:
        seen.setdefault(normalize_phrase(p), p)
    return list(seen.values())


def year_filter(cfg: Config) -> str:
    """全論文の母集団: 対象年の範囲と論文種別。"""
    f = f"publication_year:{cfg.year_from}-{cfg.year_to}"
    return f + (f",type:{cfg.work_type}" if cfg.work_type else "")


def base_filter(cfg: Config) -> str:
    """同一 subfield の母集団。

    1論文に最大3つの Topic が付くため、subfield は primary_topic 側で絞る
    (topics.subfield だと同じ論文が複数の subfield で重複計上される)。
    """
    return f"{year_filter(cfg)},primary_topic.subfield.id:{cfg.subfield_id}"


def level_filter(cfg: Config, level: str) -> str:
    if level == "all":
        return year_filter(cfg)
    if level == "field":
        return f"{year_filter(cfg)},primary_topic.field.id:{cfg.oa_field_id}"
    if level == "subfield":
        return base_filter(cfg)
    raise ValueError(f"未定義の分母: {level}")


def denominator_params(cfg: Config, level: str = "subfield") -> dict:
    """分母: 母集団の年別論文数。group_by は1リクエストにつき1つ。"""
    return {
        "filter": level_filter(cfg, level),
        "group_by": "publication_year",
        "per_page": PAGE_SIZE,
    }


def count_params(cfg: Config, query: str) -> dict:
    """検索式に一致する総件数だけを取る(meta.count を読む)。"""
    return {
        "filter": year_filter(cfg),
        cfg.search_param: query,
        "per_page": 1,
        "select": "id",
    }


def works_params(cfg: Config, phrase: str) -> dict:
    """1語句に一致する論文を cursor ページングで全件取るための初回パラメータ。

    語句は正規化して送る(大小・ハイフンの違いで同じ検索を二重に打たず、キャッシュを共有する)。
    """
    return {
        "filter": year_filter(cfg),
        cfg.search_param: quote(normalize_phrase(phrase)),
        "per_page": PAGE_SIZE,
        "select": WORK_SELECT,
        "cursor": "*",
    }
