import json

import pytest
import requests

from conftest import SECRET
from fake_openalex import FakeOpenAlex, connection_error
from openalex_trend.client import BudgetExceeded, OpenAlexError
from openalex_trend.queries import denominator_params

PARAMS = {"filter": "publication_year:2020-2023", "group_by": "publication_year"}


def test_キャッシュがあれば再実行しても通信しない(make_client):
    client, server, cfg = make_client()
    a = client.get(PARAMS)
    b = client.get(dict(PARAMS))
    assert a == b
    assert len(server.calls) == 1
    assert client.cache_hits == 1 and client.network_requests == 1


def test_APIキーは送信するがキャッシュには残さない(make_client):
    client, server, cfg = make_client()
    client.get(PARAMS)
    assert server.calls[0]["api_key"] == SECRET
    for f in cfg.cache_dir.glob("*.json"):
        assert SECRET not in f.read_text(encoding="utf-8")
        assert "api_key" not in json.loads(f.read_text(encoding="utf-8"))["params"]


def test_キーの有無でキャッシュキーが変わらない(make_client):
    client, server, cfg = make_client()
    client.get(PARAMS)
    client.get({**PARAMS, "api_key": "other"})
    assert len(server.calls) == 1


def test_429と5xxは指数バックオフで再試行する(make_client, clock):
    client, server, _ = make_client(FakeOpenAlex(fail_with=[429, 503, 500]))
    assert client.get(PARAMS)["group_by"]
    backoffs = [s for s in clock.sleeps if s >= 1]
    assert backoffs == [1.0, 2.0, 4.0]
    assert len(server.calls) == 4


def test_Retry_Afterが大きければ従う(make_client, clock):
    client, _, _ = make_client(FakeOpenAlex(fail_with=[(429, {"Retry-After": "10"})]))
    client.get(PARAMS)
    assert 10.0 in clock.sleeps


def test_リトライ上限で失敗し_メッセージにキーを含めない(make_client):
    client, server, cfg = make_client(FakeOpenAlex(fail_with=[503] * 10))
    with pytest.raises(OpenAlexError) as e:
        client.get(PARAMS)
    assert SECRET not in str(e.value)
    assert len(server.calls) == cfg.max_retries + 1
    assert not list(cfg.cache_dir.glob("*.json"))  # 失敗はキャッシュしない


def test_通信エラーの文面からキーを除く(make_client):
    client, _, _ = make_client(FakeOpenAlex(fail_with=[connection_error(SECRET)] * 10))
    with pytest.raises(OpenAlexError) as e:
        client.get(PARAMS)
    assert SECRET not in str(e.value)
    assert e.value.__cause__ is None


def test_リトライ不能なステータスは即座に失敗する(make_client):
    client, server, _ = make_client(FakeOpenAlex(fail_with=[400]))
    with pytest.raises(OpenAlexError):
        client.get(PARAMS)
    assert len(server.calls) == 1


def test_毎秒30リクエスト以内に間隔を空ける(make_client, clock):
    client, _, _ = make_client()
    for i in range(31):
        client.get({**PARAMS, "page": i})
    assert clock.now >= 30 / 30 - 1e-9  # 31リクエストの間隔30個 = 1秒以上


def test_予算を超えるリクエストは打たずに止める(make_client, make_cfg):
    cfg = make_cfg(daily_budget_usd=0.0003)  # 3リクエスト分
    client, server, _ = make_client(cfg=cfg)
    for i in range(3):
        client.get({**PARAMS, "page": i})
    client.get({**PARAMS, "page": 0})  # キャッシュ命中は数えない
    with pytest.raises(BudgetExceeded):
        client.get({**PARAMS, "page": 99})
    assert len(server.calls) == 3


def test_推定リクエスト数はキャッシュ済みを除く(make_client):
    client, _, cfg = make_client()
    client.get(denominator_params(cfg))
    plan = client.describe_plan([denominator_params(cfg), PARAMS, PARAMS], extra_unknown=2)
    assert (plan.total, plan.cached, plan.to_run) == (2, 1, 1)
    assert plan.cost_usd == pytest.approx(3 * cfg.cost_per_request_usd)
    assert "推定リクエスト数" in plan.format()


def test_壊れたキャッシュは取り直す(make_client):
    client, server, cfg = make_client()
    client.get(PARAMS)
    next(cfg.cache_dir.glob("*.json")).write_text("{broken", encoding="utf-8")
    client.get(PARAMS)
    assert len(server.calls) == 2
