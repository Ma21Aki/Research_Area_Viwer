"""年×分野の件数・比率・前年比成長率・3年移動平均を計算する。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config

MA_WINDOW = 3


def build_trend_table(
    cfg: Config, denominator: pd.Series, counts: dict[str, pd.Series]
) -> pd.DataFrame:
    """分野ごとの時系列を縦持ち(long形式)の DataFrame にまとめる。

    列: field, year, count, denominator, ratio, ratio_yoy, ratio_ma3
    - ratio = count / denominator(分母が0の年は NaN)
    - ratio_yoy = 比率の前年比成長率(前年の比率が0・欠損なら NaN)
    - ratio_ma3 = 当該年を含む直近3年の比率の単純平均(3年揃わない年は NaN)
      最新年を落とさないため、中心化ではなく後ろ向きの移動平均にしている
    """
    years = pd.Index(list(cfg.years), name="year")
    denom = denominator.reindex(years, fill_value=0).astype("int64")
    frames = []
    for f in cfg.fields:
        count = counts[f.label].reindex(years, fill_value=0).astype("int64")
        ratio = (count / denom.where(denom > 0)).astype(float)
        prev = ratio.shift(1)
        yoy = (ratio / prev - 1).replace([np.inf, -np.inf], np.nan)
        yoy[prev == 0] = np.nan
        ma3 = ratio.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
        frames.append(
            pd.DataFrame(
                {
                    "field": f.label,
                    "year": years,
                    "count": count.values,
                    "denominator": denom.values,
                    "ratio": ratio.values,
                    "ratio_yoy": yoy.values,
                    "ratio_ma3": ma3.values,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def default_trend_table(
    cfg: Config, metrics: pd.DataFrame, denominators: dict[str, pd.Series]
) -> pd.DataFrame:
    """既定の分母(default_denominator)での比率・前年比・3年移動平均の表。"""
    lv = cfg.default_denominator
    counts = {
        f.label: metrics[metrics["field"] == f.label].set_index("year")[f"count_{lv}"]
        for f in cfg.fields
    }
    return build_trend_table(cfg, denominators[lv], counts)
