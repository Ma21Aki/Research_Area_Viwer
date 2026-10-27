import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from fake_openalex import FakeOpenAlex
from openalex_trend.server import DashboardApp, make_handler


@pytest.fixture
def running(make_client, tmp_path):
    """偽サーバーにつながったローカルサーバーを空きポートで起動する。"""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    client, server, cfg = make_client()
    app = DashboardApp(cfg, client)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(app, static_root=static, port=port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    app.start(wait=True)
    yield app, server, cfg, port
    httpd.shutdown()
    httpd.server_close()


def req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    c.request(method, path, None if body is None else json.dumps(body), h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data


def wait(app):
    if app._thread:
        app._thread.join(timeout=10)


NEW_TOPICS = [
    {"id": "SSM", "headword": "state space model", "synonyms": ["dynamic linear model"], "excludes": []},
    {"id": "HB", "headword": "hierarchical Bayesian", "synonyms": [], "excludes": []},
    {"headword": "regression for sample", "synonyms": [], "excludes": []},
]


def test_起動時に集計し_画面とデータを配信する(running):
    app, _, _, port = running
    assert app.job["state"] == "done"
    status, doc = req(port, "GET", "/api/dashboard")
    assert status == 200 and [t["label"] for t in doc["topics"]] == ["SSM", "HB"]
    assert req(port, "GET", "/data/dashboard.json")[0] == 200
    status, body = req(port, "GET", "/")
    assert status == 200 and b"<title>t</title>" in body
    status, st = req(port, "GET", "/api/state")
    assert st["editable"] is True and st["has_data"] is True


def test_トピックの追加は保存して再集計する(running):
    app, _, cfg, port = running
    status, body = req(port, "PUT", "/api/topics", {"topics": NEW_TOPICS})
    assert status == 202
    wait(app)
    assert app.job["state"] == "done", app.job
    saved = json.loads(cfg.topics_path.read_text(encoding="utf-8"))
    assert [t["id"] for t in saved] == ["SSM", "HB", "RegressionForSample"]
    assert [t["color"] for t in saved] == [0, 1, 2]
    _, doc = req(port, "GET", "/api/dashboard")
    assert doc["topics"][2]["display_name"] == "regression for sample"
    assert req(port, "GET", "/api/topics")[1]["topics"] == saved


def test_除外語句の変更は通信なしで即時に再集計する(running):
    app, server, _, port = running
    n = len(server.calls)
    topics = [dict(NEW_TOPICS[0], excludes=["dynamic linear model"]), NEW_TOPICS[1]]
    assert req(port, "PUT", "/api/topics", {"topics": topics})[0] == 202
    wait(app)
    assert len(server.calls) == n  # 取得済みの語句だけなので OpenAlex に問い合わせない
    _, doc = req(port, "GET", "/api/dashboard")
    ssm = doc["topics"][0]
    assert ssm["excludes"] == [{"phrase": "dynamic linear model", "count": 4}]
    assert ssm["excluded"] == 4 and sum(ssm["series"]["count_all"]) == 14 - 4


def test_不正な定義は400で_保存しない(running):
    app, _, cfg, port = running
    before = cfg.topics_path.exists() and cfg.topics_path.read_text(encoding="utf-8")
    status, body = req(port, "PUT", "/api/topics", {"topics": [{"headword": ""}]})
    assert status == 400 and "空" in body["error"]
    assert (cfg.topics_path.exists() and cfg.topics_path.read_text(encoding="utf-8")) == before


def test_取得に失敗したら保存しない(running, make_cfg):
    app, server, cfg, port = running
    server.fail_with = [400]  # 次のリクエストがリトライ不能な失敗
    status, _ = req(port, "PUT", "/api/topics", {"topics": NEW_TOPICS})
    assert status == 202
    wait(app)
    assert app.job["state"] == "error"
    assert not cfg.topics_path.exists()
    assert [t["id"] for t in app.topics] == ["SSM", "HB"]  # 元のまま


def test_取得中は409(running):
    app, _, _, port = running
    app.job["state"] = "running"
    assert req(port, "PUT", "/api/topics", {"topics": NEW_TOPICS})[0] == 409


def test_他サイトからの書き込みとファイル外参照を拒否する(running):
    app, _, _, port = running
    assert req(port, "PUT", "/api/topics", {"topics": NEW_TOPICS}, {"Origin": "https://evil.example"})[0] == 403
    assert req(port, "GET", "/api/state", None, {"Host": "evil.example"})[0] == 403
    assert req(port, "GET", "/../secret.txt")[0] == 404
    assert req(port, "GET", "/%2e%2e/secret.txt")[0] == 404
    status, _ = req(port, "PUT", "/api/topics", None, {"Content-Type": "text/plain", "Content-Length": "2"})
    assert status == 400
