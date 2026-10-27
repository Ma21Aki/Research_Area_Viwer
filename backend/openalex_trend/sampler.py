"""精度検証用サンプラー: タイトル一致した論文から seed 固定でランダム抽出する。

`run` で取得済みの論文(キャッシュ)から手元で抽出するので、通常は追加の通信がない。
出力 CSV の label 列は空欄。手で「主題 / 非主題」を記入して適合率を確認する。
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from .client import OpenAlexClient
from .config import Config
from .works import Work, fetch_topic_works

COLUMNS = ["field", "work_id", "title", "year", "primary_topic", "label"]


def _row(label: str, w: Work) -> dict:
    return {
        "field": label,
        "work_id": w.id,
        "title": w.title,
        "year": w.year,
        "primary_topic": w.topic_name,
        "label": "",
    }


def sample_all(client: OpenAlexClient, cfg: Config) -> list[dict]:
    rows: list[dict] = []
    for f in cfg.fields:
        works = fetch_topic_works(client, cfg, f).works  # 除外語句を当てた後の論文から抽出
        ids = sorted(works)  # 取得順に依らず、同じ集合なら同じ抽出になる
        picked = random.Random(cfg.sample_seed).sample(ids, min(cfg.sample_size, len(ids)))
        rows += sorted((_row(f.label, works[i]) for i in picked), key=lambda r: r["work_id"])
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
