import csv
import json

import pandas as pd
import pytest

from fake_openalex import FakeOpenAlex, make_corpus
from openalex_trend import validation
from openalex_trend.analysis import build_trend_table
from openalex_trend.counts import (
    fetch_all,
    iter_works,
    plan_requests,
    total_count,
    union_work_years,
    yearly_counts,
)
from openalex_trend.queries import denominator_params, id_pages_params, or_query
from openalex_trend.report import plot_ratio, write_csv, write_summary_json
from openalex_trend.sampler import COLUMNS, sample_all, write_samples

# コーパスの期待値(対象 subfield・2020-2023 のみ)
DENOMINATOR = {2020: 22, 2021: 25, 2022: 38, 2023: 32}
SSM_OR = {2020: 2, 2021: 4, 2022: 5, 2023: 2}
HB = {2022: 3}


def test_分母は対象subfieldと年範囲だけを数える(make_client):
    client, _, cfg = make_client()
    s = yearly_counts(client, denominator_params(cfg))
    assert s.to_dict() == DENOMINATOR  # 別subfield・1980年は入らない


def test_or方式の年別件数(make_client):
    client, _, cfg = make_client()
    denom, counts = fetch_all(client, cfg)
    assert counts["SSM"].to_dict() == SSM_OR
    assert counts["HB"].to_dict() == HB


def test_union方式はor方式と同じ件数になる(make_client, make_cfg):
    cfg = make_cfg(query_mode="union")
    client, _, _ = make_client(cfg=cfg)
    _, counts = fetch_all(client, cfg)
    assert counts["SSM"].to_dict() == SSM_OR
    assert counts["HB"].to_dict() == HB


def test_cursorページングで全件を重複なく取る(make_client):
    client, server, cfg = make_client()
    params = {**id_pages_params(cfg, '"state space model"'), "per_page": 4}
    works = list(iter_works(client, params))
    assert len(works) == total_count(client, {**params, "per_page": 1})
    assert len({w["id"] for w in works}) == len(works)
    assert sum("cursor" in c and c["cursor"] != "*" for c in server.calls) >= 2


def test_union方式のID和集合は重複を畳む(make_client):
    client, _, cfg = make_client()
    # ハイフン表記は同じフレーズ扱いなので、語句を足しても同じIDを二重に数えない
    f = cfg.field("SSM")
    ids = union_work_years(client, cfg, f)
    assert len(ids) == sum(SSM_OR.values())


def test_推定リクエスト数_or方式は分母1と分野数(make_client):
    client, server, cfg = make_client()
    reqs, extra = plan_requests(client, cfg)
    assert len(reqs) == 1 + len(cfg.fields) and extra == 0
    assert server.calls == []  # 見積りだけでは通信しない


def test_推定リクエスト数_union方式は件数から頁数を見積もる(make_client, make_cfg):
    cfg = make_cfg(query_mode="union")
    client, _, _ = make_client(cfg=cfg)
    reqs, extra = plan_requests(client, cfg)
    assert extra == 3  # 3語句とも件数が1〜200 -> 各1頁


def test_出力ファイル(make_client, tmp_path):
    client, _, cfg = make_client()
    denom, counts = fetch_all(client, cfg)
    table = build_trend_table(cfg, denom, counts)
    out = cfg.output_dir
    csv_path = write_csv(table, out)
    json_path = write_summary_json(cfg, table, out)
    png_path = plot_ratio(cfg, table, out)
    df = pd.read_csv(csv_path)
    row = df[(df.field == "SSM") & (df.year == 2021)].iloc[0]
    assert (row["count"], row["denominator"]) == (4, 25)
    assert row["ratio"] == pytest.approx(4 / 25)
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    ssm = next(f for f in doc["fields"] if f["label"] == "SSM")
    assert ssm["years"] == [2020, 2021, 2022, 2023]
    assert ssm["ratio_ma3"][:2] == [None, None]  # 欠損は null
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ---- クエリ検証 -------------------------------------------------------
def test_検証_正しいサーバーはOK(make_client):
    client, _, cfg = make_client()
    results = validation.validate_all(client, cfg)
    assert all(r.ok for r in results), [r.failures for r in results]
    ssm = next(r for r in results if r.label == "SSM")
    assert ssm.n_or == 13  # 2020-2023 の SSM 一致の合計
    # 引用符あり < 引用符なし(語順違いの「A model of state and space」が増える)
    assert ssm.n_phrase["state space model"] < ssm.n_words["state space model"]


def test_検証_検索が無視されるとNG(make_client):
    client, _, cfg = make_client(FakeOpenAlex(search_mode="ignored"))
    results = validation.validate_all(client, cfg)
    assert not any(r.ok for r in results)
    assert "分母と同じ" in results[0].failures[0]
    assert "union" in validation.format_report(results)


def test_検証_ORが文字列として扱われるとNG(make_client):
    client, _, cfg = make_client(FakeOpenAlex(search_mode="or_literal"))
    results = validation.validate_all(client, cfg)
    ssm = next(r for r in results if r.label == "SSM")
    assert not ssm.ok and ssm.n_or == 0


def test_検証_件数の関係式():
    fails, warns = validation.check_field(10, {"a": 6, "b": 5}, {"a": 8, "b": 9}, 1000)
    assert not fails and not warns
    fails, _ = validation.check_field(20, {"a": 6, "b": 5}, {"a": 8, "b": 9}, 1000)
    assert any("合計を超える" in m for m in fails)
    fails, _ = validation.check_field(5, {"a": 6}, {"a": 8}, 1000)
    assert any("最大" in m for m in fails)
    fails, _ = validation.check_field(5, {"a": 9}, {"a": 8}, 1000)
    assert any("フレーズ件数" in m for m in fails)


def test_検証の推定リクエスト数(make_cfg):
    cfg = make_cfg()
    assert len(validation.planned_requests(cfg)) == 1 + (1 + 2 * 2) + (1 + 2 * 1)


# ---- サンプラー -------------------------------------------------------
@pytest.mark.parametrize("mode", ["or", "union"])
def test_サンプラーはseed固定で再現し_label列は空(make_client, make_cfg, mode):
    cfg = make_cfg(query_mode=mode)
    client, _, _ = make_client(cfg=cfg)
    rows = sample_all(client, cfg)
    rows2 = sample_all(client, cfg)
    assert rows == rows2
    by_field = {f.label: [r for r in rows if r["field"] == f.label] for f in cfg.fields}
    assert len(by_field["SSM"]) == 5  # sampling.size
    assert len(by_field["HB"]) == 3  # 一致が3件しかないので全件
    assert all(r["label"] == "" for r in rows)
    assert all(r["title"] and r["year"] for r in rows)
    assert len({r["work_id"] for r in rows}) == len(rows)


def test_サンプルCSVの形式(make_client, tmp_path):
    client, _, cfg = make_client()
    path = write_samples(sample_all(client, cfg), tmp_path / "samples")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert reader.fieldnames == COLUMNS
    assert rows and all(r["label"] == "" for r in rows)
    assert all(r["primary_topic"].startswith("Topic") for r in rows)


def test_サンプルのseedを変えると抽出が変わる(make_client, make_cfg):
    a = sample_all(*make_client()[:1], make_cfg())
    cfg2 = make_cfg()
    object.__setattr__(cfg2, "sample_seed", 999)
    client2, _, _ = make_client(cfg=cfg2)
    b = sample_all(client2, cfg2)
    assert {r["work_id"] for r in a} != {r["work_id"] for r in b}


# ---- 診断(subfield 分布) ----------------------------------------------
def test_診断は_subfieldで絞らずに分布を数える(make_client):
    from openalex_trend import diagnose

    client, server, cfg = make_client()
    # 別 subfield の論文もタイトルに語句があれば数える(対象 subfield だけに絞らない)
    rows = diagnose.diagnose_all(client, cfg)
    ssm = [r for r in rows if r["field"] == "SSM" and r["level"] == "subfield"]
    by_id = {r["topic_id"]: r for r in ssm}
    assert by_id["subfields/2613"]["count"] == 13
    assert by_id["subfields/9999"]["count"] == 1  # 2021年の別subfield論文(1980年は年範囲外)
    assert by_id["subfields/2613"]["is_target"] == 1 and by_id["subfields/9999"]["is_target"] == 0
    assert [r["rank"] for r in ssm] == [1, 2]
    assert sum(r["share"] for r in ssm) == pytest.approx(1.0)
    assert diagnose.target_share(rows)["SSM"] == pytest.approx(13 / 14)
    assert all("filter" in c and "primary_topic.subfield.id" not in c["filter"] for c in server.calls)


def test_診断の出力とリクエスト数(make_client, tmp_path):
    from openalex_trend import diagnose

    client, _, cfg = make_client()
    assert len(diagnose.planned_requests(cfg)) == len(cfg.fields) * 2
    rows = diagnose.diagnose_all(client, cfg)
    path = diagnose.write_csv(rows, tmp_path / "o")
    assert path.read_text(encoding="utf-8-sig").startswith("field,level,rank,topic_id")
    assert "対象 subfield に入る割合" in diagnose.format_report(rows)
