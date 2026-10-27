import json

import pytest
import yaml

from conftest import BASE_CONFIG
from openalex_trend.config import fields_from_topics, load_config, topics_from_fields
from openalex_trend.text import phrase_pattern, title_matches
from openalex_trend.topics import MAX_TOPICS, TopicError, make_id, validate_topics
from openalex_trend.works import Work, apply_excludes


def test_トピックの検証と整形():
    t = validate_topics([
        {"headword": '  state  "space" model ', "synonyms": ["State-Space Model", "dynamic linear model", "", "Dynamic Linear Model"], "excludes": ["mamba", "Mamba"]},
        {"id": "GP", "headword": "Gaussian process"},
    ])
    assert t[0]["headword"] == "state space model"
    # 見出し語句と表記違いの言い換え・重複は除く(先に書いた方を残す)
    assert t[0]["synonyms"] == ["dynamic linear model"]
    assert t[0]["excludes"] == ["mamba"]
    assert t[0]["id"] == "StateSpaceModel" and t[1]["id"] == "GP"
    assert make_id("Gaussian process", set()) == "GaussianProcess"
    assert t[1]["synonyms"] == [] and t[1]["excludes"] == []


@pytest.mark.parametrize("raw, msg", [
    ([], "1つ以上"),
    ([{"headword": ""}], "空"),
    ([{"headword": "a"}, {"headword": "A"}], "重複"),
    ([{"headword": f"t{i}"} for i in range(MAX_TOPICS + 1)], "個まで"),
    ([{"headword": "a", "synonyms": "b"}], "配列"),
    ([{"headword": "x" * 500}], "長すぎる"),
])
def test_不正なトピックは理由つきで拒否する(raw, msg):
    with pytest.raises(TopicError, match=msg):
        validate_topics(raw)


def test_IDの生成():
    assert make_id("variational inference", set()) == "VariationalInference"
    assert make_id("状態空間モデル", set()) == "Topic"
    assert make_id("GP", {"GP", "GP2"}) == "GP3"
    # 不正なIDや重複IDは作り直す
    t = validate_topics([{"id": "../x", "headword": "a b"}, {"id": "AB", "headword": "c"}, {"id": "AB", "headword": "d"}])
    assert [x["id"] for x in t] == ["AB", "C", "D"]


def test_除外語句は単語単位で複数形も一致():
    assert title_matches("Mamba-based selective models", phrase_pattern("mamba"))
    assert title_matches("Vision Transformers for time series", phrase_pattern("transformer"))
    assert title_matches("A deep-learning approach", phrase_pattern("deep learning"))
    assert not title_matches("An annual state space model", phrase_pattern("nn"))
    assert title_matches("NN-based filtering", phrase_pattern("nn"))
    assert not title_matches("Transformation of variables", phrase_pattern("transformer"))


def test_除外の適用と件数():
    def w(i, title):
        return Work(id=f"W{i}", title=title, year=2024, cited_by_count=0)
    works = {x.id: x for x in [w(1, "Mamba: linear-time"), w(2, "Mamba and Transformer"), w(3, "Kalman smoothing")]}
    kept, counts = apply_excludes(works, ["mamba", "transformer", "lstm"])
    assert list(kept) == ["W3"]
    assert counts == {"mamba": 2, "transformer": 1, "lstm": 0}


def test_設定はtopics_jsonから読む(tmp_path):
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    del raw["fields"]
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "topics.json").write_text(json.dumps([
        {"id": "SSM", "headword": "state space model", "synonyms": ["dynamic linear model"], "excludes": ["mamba"]},
    ]), encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml", root=tmp_path)
    f = cfg.fields[0]
    assert (f.label, f.display_name, f.phrases, f.excludes) == (
        "SSM", "state space model", ("state space model", "dynamic linear model"), ("mamba",))
    assert topics_from_fields(fields_from_topics(validate_topics(json.loads((tmp_path / "topics.json").read_text())))) == [
        {"id": "SSM", "headword": "state space model", "synonyms": ["dynamic linear model"], "excludes": ["mamba"], "color": 0}]


def test_リポジトリのtopics_jsonは有効():
    from openalex_trend.config import REPO_ROOT
    from openalex_trend.topics import load_topics

    topics = load_topics(REPO_ROOT / "topics.json")
    assert [t["id"] for t in topics] == ["SSM", "HierBayes", "GP", "VI", "CausalInference"]


def test_色はトピックに固定し_空いている色を割り当てる():
    t = validate_topics([{"headword": "a", "color": 2}, {"headword": "b"}, {"headword": "c", "color": 2}, {"headword": "d", "color": 0}])
    assert [x["color"] for x in t] == [2, 1, 3, 0]
