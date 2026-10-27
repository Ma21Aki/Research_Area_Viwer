"""トピック×年の指標表を作る。分母の切替・被引用の指標はここで手元集計する。

指標(年ごと):
  count_all / count_field / count_subfield  タイトル一致の論文数(母集団を全論文 / field / subfield に絞った数)
  cites_received   その年に、一致した論文が受けた被引用数(引用された年で集計)
  mean_cites       その出版年の論文の、1論文あたり累計被引用数(新しい論文ほど不利)
  fwci_mean        FWCI(分野・年・種別で正規化した被引用)の平均
  top10_share      被引用上位10%に入る論文の割合
被引用の年別内訳が取れていない年は None(0 ではない)にする。
"""

from __future__ import annotations

import math

import pandas as pd

from .config import Config
from .queries import LEVELS
from .works import Work

METRIC_COLUMNS = [
    "count_all", "count_field", "count_subfield",
    "cites_received", "mean_cites", "fwci_mean", "top10_share",
]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def topic_year_table(cfg: Config, label: str, works: dict[str, Work], covered: set[int]) -> pd.DataFrame:
    """1トピックの年別指標。covered は被引用の年別内訳が1件でも取れた年の集合。"""
    rows = []
    for y in cfg.years:
        ws = [w for w in works.values() if w.year == y]
        fwci = [w.fwci for w in ws if w.fwci is not None]
        top = [w.top10 for w in ws if w.top10 is not None]
        rows.append(
            {
                "field": label,
                "year": y,
                "count_all": len(ws),
                "count_field": sum(w.field_id == cfg.oa_field_id for w in ws),
                "count_subfield": sum(w.subfield_id == cfg.subfield_id for w in ws),
                "cites_received": (
                    sum(w.cites_by_year.get(y, 0) for w in works.values()) if y in covered else None
                ),
                "mean_cites": _mean([w.cited_by_count for w in ws]),
                "fwci_mean": _mean(fwci),
                "top10_share": _mean([float(t) for t in top]),
            }
        )
    return pd.DataFrame(rows)


def covered_years(topic_works: dict[str, dict[str, Work]]) -> set[int]:
    """被引用の年別内訳(counts_by_year)が取れている年。全トピックを通して判定する。"""
    return {y for works in topic_works.values() for w in works.values() for y in w.cites_by_year}


def build_metrics(cfg: Config, topic_works: dict[str, dict[str, Work]]) -> pd.DataFrame:
    covered = covered_years(topic_works)
    return pd.concat(
        [topic_year_table(cfg, f.label, topic_works[f.label], covered) for f in cfg.fields],
        ignore_index=True,
    )


def add_ratios(cfg: Config, metrics: pd.DataFrame, denominators: dict[str, pd.Series]) -> pd.DataFrame:
    """分母(年別論文数)と出現率の列を足す。分母が0の年は NaN。"""
    out = metrics.copy()
    for lv in LEVELS:
        d = denominators[lv].reindex(list(cfg.years), fill_value=0)
        out[f"denom_{lv}"] = out["year"].map(d).astype("int64")
        denom = out[f"denom_{lv}"].where(out[f"denom_{lv}"] > 0)
        out[f"ratio_{lv}"] = out[f"count_{lv}"] / denom
    return out


def nullable(values) -> list[float | None]:
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v) else float(v) for v in values]
