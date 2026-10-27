import csv
import json

import pandas as pd
import pytest

from fake_openalex import FakeOpenAlex, make_corpus
from openalex_trend import diagnose, validation
from openalex_trend.analysis import default_trend_table
from openalex_trend.counts import fetch_denominators, iter_works, total_count
from openalex_trend.pipeline import build
from openalex_trend.queries import (
    count_params,
    normalize_phrase,
    unique_phrases,
    works_params,
    year_filter,
)
from openalex_trend.report import (
    plot_ratio,
    write_csv,
    write_dashboard_json,
    write_metrics_csv,
)
from openalex_trend.sampler import COLUMNS, sample_all, write_samples
from openalex_trend.works import fetch_topic_works, plan_requests

YEARS = [2020, 2021, 2022, 2023]
SSM_PHRASES = ["state space model", "state-space model", "dynamic linear model"]


def _by_year(works, pred=lambda w: True):
    """コーパスから独立に数える(実装と同じ式を使わない)。"""
    out = {y: 0 for y in YEARS}
    for w in works:
        if w["publication_year"] in out and pred(w):
            out[w["publication_year"]] += 1
    return [out[y] for y in YEARS]


def _is_ssm(w):
    t = w["title"].lower().replace("-", " ")
    return "state space model" in t or "dynamic linear model" in t


def _build(client, cfg):
    r = build(client, cfg)
    return r.denominators, r.fetched, r.doc, r.metrics


# ---- 分母(3水準) -------------------------------------------------------
def test_分母は全論文_field_subfieldの3水準(make_client):
    client, _, cfg = make_client()
    d = fetch_denominators(client, cfg)
    corpus = make_corpus()
    assert d["all"].reindex(YEARS, fill_value=0).tolist() == _by_year(corpus)
    in_field = lambda w: w["primary_topic"]["field"]["id"].endswith("fields/26")
    in_sub = lambda w: w["primary_topic"]["subfield"]["id"].endswith("subfields/2613")
    assert d["field"].reindex(YEARS, fill_value=0).tolist() == _by_year(corpus, in_field)
    assert d["subfield"].reindex(YEARS, fill_value=0).tolist() == _by_year(corpus, in_sub)
    # 別 field の1件があるので、all は subfield より多い(2021年)
    assert d["all"][2021] == d["subfield"][2021] + 1


def test_論文種別で絞ると分母にも分子にも効く(make_cfg, make_client):
    corpus = make_corpus()
    pre = dict(corpus[0], id="https://openalex.org/W9999", type="preprint")
    server = FakeOpenAlex(corpus + [pre])
    cfg_all = make_cfg()  # 種別で絞らない
    c1, _, _ = make_client(server, cfg_all)
    assert year_filter(cfg_all) == "publication_year:2020-2023"
    n_all = total_count(c1, count_params(cfg_all, '"state space model"'))
    cfg_art = make_cfg(population={"work_type": "article"})
    c2, _, _ = make_client(FakeOpenAlex(corpus + [pre]), cfg_art)
    assert year_filter(cfg_art).endswith("type:article")
    assert total_count(c2, count_params(cfg_art, '"state space model"')) == n_all - 1
    assert fetch_denominators(c2, cfg_art)["all"].sum() == sum(_by_year(corpus))


# ---- 語句ごとの取得と和集合 -----------------------------------------------
def test_語句ごとに取得し_work_IDで和集合を取る(make_client):
    client, _, cfg = make_client()
    tf = fetch_topic_works(client, cfg, cfg.field("SSM"))
    works, per_phrase = tf.works, tf.phrase_counts
    assert len(works) == sum(_by_year(make_corpus(), _is_ssm))
    # ハイフン違いは同一視して1回だけ取得し、重複を数えない
    assert set(per_phrase) == {"state space model", "dynamic linear model"}
    assert per_phrase == {"state space model": 10, "dynamic linear model": 4}


def test_語句の正規化(make_cfg):
    assert normalize_phrase(" State-Space  Model ") == "state space model"
    assert unique_phrases(SSM_PHRASES) == ["state space model", "dynamic linear model"]


def test_cursorページングで全件を重複なく取る(make_client):
    client, server, cfg = make_client()
    params = {**works_params(cfg, "state space model"), "per_page": 4}
    works = list(iter_works(client, params))
    assert len(works) == total_count(client, count_params(cfg, '"state space model"'))
    assert len({w["id"] for w in works}) == len(works)
    assert sum("cursor" in c and c["cursor"] != "*" for c in server.calls) >= 2


# ---- 指標 ----------------------------------------------------------------
def test_論文数はscopeごとに数える(make_client):
    client, _, cfg = make_client()
    *_, metrics = _build(client, cfg)
    ssm = metrics[metrics["field"] == "SSM"].set_index("year")
    corpus = make_corpus()
    in_field = lambda w: w["primary_topic"]["field"]["id"].endswith("fields/26")
    in_sub = lambda w: w["primary_topic"]["subfield"]["id"].endswith("subfields/2613")
    assert ssm["count_all"].tolist() == _by_year(corpus, _is_ssm)
    assert ssm["count_field"].tolist() == _by_year(corpus, lambda w: _is_ssm(w) and in_field(w))
    assert ssm["count_subfield"].tolist() == _by_year(corpus, lambda w: _is_ssm(w) and in_sub(w))


def test_被引用の指標(make_client):
    client, _, cfg = make_client()
    *_, metrics = _build(client, cfg)
    ssm = metrics[metrics["field"] == "SSM"].set_index("year")
    ws = [w for w in make_corpus() if _is_ssm(w) and 2020 <= w["publication_year"] <= 2023]
    # その年に受けた被引用: 内訳が取れた年(2022, 2023)だけ値があり、取れていない年は None
    assert pd.isna(ssm["cites_received"][2020]) and pd.isna(ssm["cites_received"][2021])
    for y in (2022, 2023):
        expect = sum(c["cited_by_count"] for w in ws for c in w["counts_by_year"] if c["year"] == y)
        assert ssm["cites_received"][y] == expect
    for y in YEARS:
        cohort = [w for w in ws if w["publication_year"] == y]
        assert ssm["mean_cites"][y] == pytest.approx(sum(w["cited_by_count"] for w in cohort) / len(cohort))
        fw = [w["fwci"] for w in cohort if w["fwci"] is not None]
        assert ssm["fwci_mean"][y] == pytest.approx(sum(fw) / len(fw))
        top = [w["citation_normalized_percentile"]["is_in_top_10_percent"] for w in cohort]
        assert ssm["top10_share"][y] == pytest.approx(sum(top) / len(top))


def test_出現率は3つの分母ごとに計算する(make_client):
    client, _, cfg = make_client()
    denominators, _, _, metrics = _build(client, cfg)
    row = metrics[(metrics["field"] == "SSM") & (metrics["year"] == 2021)].iloc[0]
    assert row["denom_all"] == denominators["all"][2021] and row["denom_subfield"] == denominators["subfield"][2021]
    assert row["ratio_all"] == pytest.approx(row["count_all"] / row["denom_all"])
    assert row["ratio_subfield"] == pytest.approx(row["count_subfield"] / row["denom_subfield"])
    # 手計算(2021年): 全論文は 5/26(別subfieldの1件を含む)、subfield は 4/25
    assert (row["count_all"], row["denom_all"]) == (5, 26)
    assert (row["count_subfield"], row["denom_subfield"]) == (4, 25)


# ---- 出力 ----------------------------------------------------------------
def test_出力ファイル(make_client):
    client, _, cfg = make_client()
    F = type(cfg.fields[0])
    object.__setattr__(cfg, "fields", (F("SSM", "State space model", tuple(SSM_PHRASES)), cfg.fields[1]))
    denominators, _, doc_built, metrics = _build(client, cfg)
    out = cfg.output_dir
    trend = default_trend_table(cfg, metrics, denominators)
    assert list(trend.columns) == [
        "field", "year", "count", "denominator", "ratio", "ratio_yoy", "ratio_ma3",
    ]
    csv_path = write_csv(trend, out)
    m_path = write_metrics_csv(metrics, out)
    j_path = write_dashboard_json(doc_built, out)
    png = plot_ratio(cfg, trend, out)
    row = pd.read_csv(csv_path).query("field == 'SSM' and year == 2021").iloc[0]
    assert row["ratio"] == pytest.approx(row["count"] / row["denominator"])
    assert "ratio_all" in pd.read_csv(m_path).columns
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    doc = json.loads(j_path.read_text(encoding="utf-8"))
    assert doc["years"] == YEARS and doc["default_denominator"] == "all"
    assert set(doc["denominators"]) == {"all", "field", "subfield"}
    assert doc["denominators"]["subfield"]["name"] == "Statistics and Probability"
    ssm = next(t for t in doc["topics"] if t["label"] == "SSM")
    assert ssm["series"]["cites_received"][:2] == [None, None]  # 欠損は null
    assert ssm["series"]["count_all"] == _by_year(make_corpus(), _is_ssm)
    phr = {p["phrase"]: p for p in ssm["phrases"]}
    assert phr["state-space model"]["merged_into"] == "state space model"
    assert phr["state space model"]["count"] == 10 and phr["state space model"]["merged_into"] is None


# ---- キャッシュ(トピック・語句の追加で再検索しない) -------------------------
def _gp_field():
    return {"label": "GPX", "display_name": "Other topic", "phrases": ["regression for sample"]}


def test_トピックを追加しても既存トピックは再検索しない(make_cfg, make_client):
    cfg1 = make_cfg()
    c1, s1, _ = make_client(cfg=cfg1)
    _build(c1, cfg1)
    first_calls = len(s1.calls)
    assert first_calls > 0

    cfg2 = make_cfg(extra_fields=[_gp_field()])  # 同じキャッシュ先 + 新トピック
    server2 = FakeOpenAlex()
    c2, _, _ = make_client(server2, cfg2)
    _build(c2, cfg2)
    assert server2.calls, "新トピックの分は取得する"
    assert all("regression for sample" in str(c.get("search.title", "")).lower() for c in server2.calls)


def test_既存トピックに語句を足すと新しい語句だけ取得する(make_cfg, make_client):
    cfg1 = make_cfg()
    c1, _, _ = make_client(cfg=cfg1)
    _build(c1, cfg1)
    raw_fields = [
        {"label": "SSM", "display_name": "State space model",
         "phrases": ["state space model", "state-space model", "dynamic linear model", "hierarchical Bayesian"]},
        {"label": "HB", "display_name": "Hierarchical Bayes", "phrases": ["hierarchical Bayesian"]},
    ]
    cfg2 = make_cfg()
    object.__setattr__(cfg2, "fields", tuple(type(cfg2.fields[0])(f["label"], f["display_name"], tuple(f["phrases"])) for f in raw_fields))
    server2 = FakeOpenAlex()
    c2, _, _ = make_client(server2, cfg2)
    _build(c2, cfg2)
    # "hierarchical Bayesian" は HB トピックで取得済み(語句単位のキャッシュ)なので通信しない
    assert server2.calls == []


def test_見積りはキャッシュ済みの語句を除く(make_cfg, make_client):
    cfg = make_cfg()
    client, server, _ = make_client(cfg=cfg)
    reqs, pages = plan_requests(client, cfg)
    assert pages == 3  # 未取得の3語句(ハイフン違いは同一視)がそれぞれ1ページ
    assert len(reqs) == 3 + 3
    _build(client, cfg)
    reqs2, pages2 = plan_requests(client, cfg)
    assert pages2 == 0 and len(reqs2) == 3  # 取得済みの語句は見積りに入らない(分母3水準のみ)


# ---- クエリ検証 -------------------------------------------------------
def test_検証_正しいサーバーはOK(make_client):
    client, _, cfg = make_client()
    results = validation.validate_all(client, cfg)
    assert all(r.ok for r in results), [r.failures for r in results]
    ssm = next(r for r in results if r.label == "SSM")
    assert ssm.n_or == sum(_by_year(make_corpus(), _is_ssm))
    assert ssm.n_phrase["state space model"] < ssm.n_words["state space model"]


def test_検証_検索が無視されるとNG(make_client):
    client, _, cfg = make_client(FakeOpenAlex(search_mode="ignored"))
    results = validation.validate_all(client, cfg)
    assert not any(r.ok for r in results)
    assert "分母と同じ" in results[0].failures[0]


def test_検証_ORが文字列として扱われるとNG(make_client):
    client, _, cfg = make_client(FakeOpenAlex(search_mode="or_literal"))
    ssm = next(r for r in validation.validate_all(client, cfg) if r.label == "SSM")
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


# ---- 診断(subfield 分布) ----------------------------------------------
def test_診断は_subfieldで絞らずに分布を数える(make_client):
    client, server, cfg = make_client()
    rows = diagnose.diagnose_all(client, cfg)
    ssm = [r for r in rows if r["field"] == "SSM" and r["level"] == "subfield"]
    by_id = {r["topic_id"]: r for r in ssm}
    assert by_id["subfields/2613"]["count"] == 13
    assert by_id["subfields/9999"]["count"] == 1  # 2021年の別subfield論文(1980年は年範囲外)
    assert by_id["subfields/2613"]["is_target"] == 1 and by_id["subfields/9999"]["is_target"] == 0
    assert [r["rank"] for r in ssm] == [1, 2]
    assert sum(r["share"] for r in ssm) == pytest.approx(1.0)
    assert diagnose.target_share(rows)["SSM"] == pytest.approx(13 / 14)
    assert all("primary_topic.subfield.id" not in c["filter"] for c in server.calls)


def test_診断の出力とリクエスト数(make_client, tmp_path):
    client, _, cfg = make_client()
    assert len(diagnose.planned_requests(cfg)) == len(cfg.fields) * 2
    rows = diagnose.diagnose_all(client, cfg)
    path = diagnose.write_csv(rows, tmp_path / "o")
    assert path.read_text(encoding="utf-8-sig").startswith("field,level,rank,topic_id")
    assert "対象 subfield に入る割合" in diagnose.format_report(rows)


# ---- サンプラー -------------------------------------------------------
def test_サンプラーはseed固定で再現し_label列は空_追加通信なし(make_client):
    client, server, cfg = make_client()
    rows = sample_all(client, cfg)
    n_calls = len(server.calls)
    assert sample_all(client, cfg) == rows
    assert len(server.calls) == n_calls  # 2回目はキャッシュだけ
    by_field = {f.label: [r for r in rows if r["field"] == f.label] for f in cfg.fields}
    assert len(by_field["SSM"]) == 5  # sampling.size
    assert len(by_field["HB"]) == 3  # 一致が3件しかないので全件
    assert all(r["label"] == "" for r in rows)
    assert all(r["title"] and r["year"] and r["primary_topic"] for r in rows)
    assert len({r["work_id"] for r in rows}) == len(rows)


def test_サンプルCSVの形式(make_client, tmp_path):
    client, _, cfg = make_client()
    path = write_samples(sample_all(client, cfg), tmp_path / "samples")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert reader.fieldnames == COLUMNS
    assert rows and all(r["label"] == "" for r in rows)


def test_サンプルのseedを変えると抽出が変わる(make_client, make_cfg):
    client, _, cfg = make_client()
    a = sample_all(client, cfg)
    object.__setattr__(cfg, "sample_seed", 999)
    b = sample_all(client, cfg)
    assert {r["work_id"] for r in a} != {r["work_id"] for r in b}
