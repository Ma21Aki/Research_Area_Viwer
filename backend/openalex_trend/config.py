"""config.yaml の読み込みと検証。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# backend/openalex_trend/config.py -> リポジトリルート
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "backend" / "config.yaml"


@dataclass(frozen=True)
class Field:
    """比較対象の研究分野。phrases は OR でまとめる同義語・表記揺れ。"""

    label: str
    display_name: str
    phrases: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    base_url: str
    search_param: str
    rate_limit_per_sec: float
    max_retries: int
    timeout_sec: float
    cost_per_request_usd: float
    daily_budget_usd: float
    work_type: str | None
    default_denominator: str
    oa_field_id: str
    oa_field_name: str
    subfield_id: str
    subfield_name: str
    year_from: int
    year_to: int
    fields: tuple[Field, ...]
    sample_size: int
    sample_seed: int
    cache_dir: Path
    output_dir: Path

    @property
    def years(self) -> range:
        return range(self.year_from, self.year_to + 1)

    def field(self, label: str) -> Field:
        for f in self.fields:
            if f.label == label:
                return f
        raise KeyError(f"未定義の分野ラベル: {label}")


def load_config(path: Path | str = DEFAULT_CONFIG, root: Path = REPO_ROOT) -> Config:
    """YAML を読んで Config を返す。不正な設定は ValueError にする。"""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    api, pop = raw["openalex"], raw["population"]
    fields = tuple(
        Field(f["label"], f.get("display_name", f["label"]), tuple(f["phrases"]))
        for f in raw["fields"]
    )
    cfg = Config(
        base_url=api["base_url"],
        search_param=api.get("search_param", "search.title"),
        rate_limit_per_sec=float(api.get("rate_limit_per_sec", 30)),
        max_retries=int(api.get("max_retries", 5)),
        timeout_sec=float(api.get("timeout_sec", 30)),
        cost_per_request_usd=float(api.get("cost_per_request_usd", 0.0001)),
        daily_budget_usd=float(api.get("daily_budget_usd", 1.0)),
        work_type=pop.get("work_type"),
        default_denominator=pop.get("default_denominator", "all"),
        oa_field_id=pop["field_id"],
        oa_field_name=pop.get("field_name", pop["field_id"]),
        subfield_id=pop["subfield_id"],
        subfield_name=pop.get("subfield_name", pop["subfield_id"]),
        year_from=int(pop["year_from"]),
        year_to=int(pop["year_to"]),
        fields=fields,
        sample_size=int(raw.get("sampling", {}).get("size", 100)),
        sample_seed=int(raw.get("sampling", {}).get("seed", 0)),
        cache_dir=root / raw["paths"]["cache_dir"],
        output_dir=root / raw["paths"]["output_dir"],
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.default_denominator not in ("all", "field", "subfield"):
        raise ValueError("default_denominator は all / field / subfield のいずれか")
    if cfg.year_from > cfg.year_to:
        raise ValueError("year_from は year_to 以下にすること")
    if cfg.rate_limit_per_sec > 30:
        raise ValueError("rate_limit_per_sec は毎秒30以内にすること")
    labels = [f.label for f in cfg.fields]
    if len(set(labels)) != len(labels):
        raise ValueError("分野ラベルが重複している")
    for f in cfg.fields:
        if not f.phrases or any(not p.strip() for p in f.phrases):
            raise ValueError(f"{f.label}: 語句が空")
