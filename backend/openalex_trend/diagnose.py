"""診断: タイトル一致した論文が、実際にどの subfield / field に主分類されているか。

分母を Statistics and Probability に絞る設計の妥当性を確かめるための集計。
subfield で絞らずに group_by=primary_topic.<level>.id で数える(分野×階層で各1リクエスト)。
"""

from __future__ import annotations

import csv
from pathlib import Path

from .client import OpenAlexClient
from .config import Config, Field
from .queries import PAGE_SIZE, or_query, year_filter

LEVELS = {"subfield": "primary_topic.subfield.id", "field": "primary_topic.field.id"}
COLUMNS = ["field", "level", "rank", "topic_id", "topic_name", "count", "share", "is_target"]


def params_for(cfg: Config, f: Field, group_by: str) -> dict:
    """subfield では絞らず、対象年の範囲とタイトル検索だけで集計する。"""
    return {
        "filter": year_filter(cfg),
        cfg.search_param: or_query(f.phrases),
        "group_by": group_by,
        "per_page": PAGE_SIZE,
    }


def planned_requests(cfg: Config) -> list[dict]:
    return [params_for(cfg, f, g) for f in cfg.fields for g in LEVELS.values()]


def _short_id(key: str) -> str:
    """https://openalex.org/subfields/2613 -> subfields/2613"""
    return key.split("openalex.org/")[-1]


def diagnose_all(client: OpenAlexClient, cfg: Config) -> list[dict]:
    rows: list[dict] = []
    for f in cfg.fields:
        for level, group_by in LEVELS.items():
            groups = client.get(params_for(cfg, f, group_by))["group_by"]
            total = sum(int(g["count"]) for g in groups) or 1
            ordered = sorted(groups, key=lambda g: -int(g["count"]))
            for rank, g in enumerate(ordered, 1):
                tid = _short_id(str(g["key"]))
                rows.append(
                    {
                        "field": f.label,
                        "level": level,
                        "rank": rank,
                        "topic_id": tid,
                        "topic_name": g.get("key_display_name", ""),
                        "count": int(g["count"]),
                        "share": int(g["count"]) / total,
                        "is_target": int(level == "subfield" and tid == cfg.subfield_id),
                    }
                )
    return rows


def target_share(rows: list[dict]) -> dict[str, float]:
    """分野ごとに、対象 subfield に主分類された割合(分母に絞った母集団が捉えている割合)。"""
    return {r["field"]: r["share"] for r in rows if r["is_target"]}


def format_report(rows: list[dict], top: int = 5) -> str:
    lines = []
    for label in dict.fromkeys(r["field"] for r in rows):
        for level in LEVELS:
            part = [r for r in rows if r["field"] == label and r["level"] == level]
            head = ", ".join(f"{r['topic_name']} {r['share']:.0%}" for r in part[:top])
            lines.append(f"{label} [{level}]: {head}")
        got = target_share(rows).get(label, 0.0)
        lines.append(f"  -> 対象 subfield に入る割合: {got:.0%}")
    return "\n".join(lines)


def write_csv(rows: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "subfield_distribution.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path
