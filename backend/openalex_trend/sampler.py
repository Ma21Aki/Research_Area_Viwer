"""精度検証用サンプラー: タイトル一致した論文から seed 固定でランダム抽出する。

出力 CSV の label 列は空欄。手で「主題 / 非主題」を記入して適合率を確認する。
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from .client import OpenAlexClient
from .config import Config, Field
from .counts import union_work_years
from .queries import PAGE_SIZE, base_filter, or_query

SELECT = "id,title,publication_year,primary_topic"
COLUMNS = ["field", "work_id", "title", "year", "primary_topic", "label"]
IDS_PER_REQUEST = 100  # ids を OR で並べるフィルタの上限


def _row(label: str, w: dict) -> dict:
    topic = w.get("primary_topic") or {}
    return {
        "field": label,
        "work_id": w["id"],
        "title": w.get("title") or "",
        "year": w.get("publication_year", ""),
        "primary_topic": topic.get("display_name", ""),
        "label": "",
    }


def _sample_or(client: OpenAlexClient, cfg: Config, f: Field) -> list[dict]:
    """or方式: OpenAlex の sample + seed で抽出する(サーバー側で再現可能)。"""
    rows: list[dict] = []
    pages = -(-cfg.sample_size // PAGE_SIZE)
    for page in range(1, pages + 1):
        data = client.get(
            {
                "filter": base_filter(cfg),
                cfg.search_param: or_query(f.phrases),
                "sample": cfg.sample_size,
                "seed": cfg.sample_seed,
                "per_page": min(PAGE_SIZE, cfg.sample_size),
                "page": page,
                "select": SELECT,
            }
        )
        rows += [_row(f.label, w) for w in data["results"]]
    return rows[: cfg.sample_size]


def _sample_union(client: OpenAlexClient, cfg: Config, f: Field) -> list[dict]:
    """union方式: 和集合の work ID から手元で抽出し、その本体だけ取得する。"""
    ids = sorted(union_work_years(client, cfg, f))
    picked = random.Random(cfg.sample_seed).sample(ids, min(cfg.sample_size, len(ids)))
    rows: list[dict] = []
    for i in range(0, len(picked), IDS_PER_REQUEST):
        chunk = [x.rsplit("/", 1)[-1] for x in picked[i : i + IDS_PER_REQUEST]]
        data = client.get(
            {
                "filter": "openalex:" + "|".join(chunk),
                "per_page": IDS_PER_REQUEST,
                "select": SELECT,
            }
        )
        rows += [_row(f.label, w) for w in data["results"]]
    return rows


def sample_all(client: OpenAlexClient, cfg: Config) -> list[dict]:
    rows: list[dict] = []
    for f in cfg.fields:
        part = _sample_or(client, cfg, f) if cfg.query_mode == "or" else _sample_union(client, cfg, f)
        rows += sorted(part, key=lambda r: r["work_id"])
    return rows


def write_samples(rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "precision_samples.csv"
    # Excel(iPhoneのNumbers等)で日本語環境でも文字化けしにくいよう BOM 付き UTF-8
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path
