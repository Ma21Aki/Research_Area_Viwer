"""取得から集計までの一連の処理(CLI の run とローカルサーバーで共用)。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .client import OpenAlexClient
from .config import Config
from .counts import fetch_denominators
from .dataset import add_ratios, build_metrics
from .report import dashboard_doc
from .works import PhraseFetcher, TopicFetch, fetch_phrase_works, fetch_topic_works


@dataclass
class Result:
    denominators: dict[str, pd.Series]
    fetched: dict[str, TopicFetch]
    metrics: pd.DataFrame
    doc: dict


def build(client: OpenAlexClient, cfg: Config, fetch_phrase: PhraseFetcher = fetch_phrase_works) -> Result:
    denominators = fetch_denominators(client, cfg)
    # 取得済みの語句はキャッシュから読むので、新しい語句の分だけ通信する
    fetched = {f.label: fetch_topic_works(client, cfg, f, fetch_phrase) for f in cfg.fields}
    metrics = add_ratios(cfg, build_metrics(cfg, {k: v.works for k, v in fetched.items()}), denominators)
    return Result(denominators, fetched, metrics, dashboard_doc(cfg, metrics, denominators, fetched))
