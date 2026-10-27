import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_openalex import FakeOpenAlex  # noqa: E402
from openalex_trend.client import OpenAlexClient  # noqa: E402
from openalex_trend.config import load_config  # noqa: E402

SECRET = "SECRET-KEY-123"

BASE_CONFIG = {
    "openalex": {
        "base_url": "https://api.openalex.org/works",
        "search_param": "search.title",
        "query_mode": "or",
        "rate_limit_per_sec": 30,
        "max_retries": 5,
        "cost_per_request_usd": 0.0001,
        "daily_budget_usd": 1.0,
    },
    "population": {
        "subfield_id": "subfields/2613",
        "subfield_name": "Statistics and Probability",
        "year_from": 2020,
        "year_to": 2023,
    },
    "fields": [
        {
            "label": "SSM",
            "display_name": "State space model",
            "phrases": ["state space model", "dynamic linear model"],
        },
        {
            "label": "HB",
            "display_name": "Hierarchical Bayes",
            "phrases": ["hierarchical Bayesian"],
        },
    ],
    "sampling": {"size": 5, "seed": 1},
    "paths": {"cache_dir": "data/cache", "output_dir": "outputs"},
}


@pytest.fixture
def make_cfg(tmp_path):
    def _make(**openalex_overrides):
        raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
        raw["openalex"].update(openalex_overrides)
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        return load_config(path, root=tmp_path)

    return _make


class FakeClock:
    """sleep で時間が進む偽の時計。待機時間を実際には待たずに検証できる。"""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, sec):
        self.sleeps.append(sec)
        self.now += sec

    def monotonic(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_client(make_cfg, clock):
    def _make(server=None, cfg=None, **kw):
        server = server or FakeOpenAlex()
        cfg = cfg or make_cfg()
        client = OpenAlexClient(
            cfg, api_key=SECRET, session=server, sleep=clock.sleep, clock=clock.monotonic, **kw
        )
        return client, server, cfg

    return _make
