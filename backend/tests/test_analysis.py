import math

import pandas as pd
import pytest

from openalex_trend.analysis import build_trend_table
from openalex_trend.queries import base_filter, or_query, quote


def _table(make_cfg, denom, counts):
    cfg = make_cfg()
    c = {f.label: pd.Series(counts.get(f.label, {}), dtype="int64") for f in cfg.fields}
    return build_trend_table(cfg, pd.Series(denom, dtype="int64"), c)


def test_比率_前年比_3年移動平均を手計算と照合する(make_cfg):
    t = _table(
        make_cfg,
        {2020: 100, 2021: 200, 2022: 200, 2023: 400},
        {"SSM": {2020: 1, 2021: 4, 2022: 6, 2023: 8}},
    )
    s = t[t["field"] == "SSM"].set_index("year")
    assert s["ratio"].tolist() == pytest.approx([0.01, 0.02, 0.03, 0.02])
    assert math.isnan(s["ratio_yoy"][2020])
    assert s["ratio_yoy"].loc[2021:].tolist() == pytest.approx([1.0, 0.5, -1 / 3])
    assert s["ratio_ma3"].isna().tolist() == [True, True, False, False]
    assert s["ratio_ma3"][2022] == pytest.approx(0.02)
    assert s["ratio_ma3"][2023] == pytest.approx((0.02 + 0.03 + 0.02) / 3)


def test_欠けた年は件数0_分母0の年は比率NaN(make_cfg):
    t = _table(make_cfg, {2020: 100, 2022: 100}, {"SSM": {2020: 5}})
    s = t[t["field"] == "SSM"].set_index("year")
    assert s["count"].tolist() == [5, 0, 0, 0]
    assert s["denominator"].tolist() == [100, 0, 100, 0]
    assert s["ratio"][2020] == pytest.approx(0.05)
    assert math.isnan(s["ratio"][2021]) and math.isnan(s["ratio"][2023])
    assert s["ratio"][2022] == 0


def test_前年の比率が0なら成長率はNaN_infにしない(make_cfg):
    t = _table(
        make_cfg, {y: 100 for y in range(2020, 2024)}, {"SSM": {2021: 0, 2022: 3}}
    )
    s = t[t["field"] == "SSM"].set_index("year")
    assert math.isnan(s["ratio_yoy"][2022])
    assert not s["ratio_yoy"].isin([float("inf"), float("-inf")]).any()


def test_全分野が縦持ちで並ぶ(make_cfg):
    t = _table(make_cfg, {2020: 10, 2021: 10, 2022: 10, 2023: 10}, {})
    assert list(t.columns) == [
        "field", "year", "count", "denominator", "ratio", "ratio_yoy", "ratio_ma3",
    ]
    assert t["field"].unique().tolist() == ["SSM", "HB"]
    assert len(t) == 8


def test_クエリ組み立て(make_cfg):
    cfg = make_cfg()
    assert quote(' "a b" ') == '"a b"'
    assert or_query(["state space model", "dynamic linear model"]) == (
        '"state space model" OR "dynamic linear model"'
    )
    f = base_filter(cfg)
    # 重複計上を避けるため primary_topic 側で絞る
    assert "primary_topic.subfield.id:subfields/2613" in f
    assert "topics.subfield" not in f
    assert "publication_year:2020-2023" in f
