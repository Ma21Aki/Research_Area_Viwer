"""コマンドライン: plan / run / validate / sample。

使い方(backend/ で実行):
    export OPENALEX_API_KEY=xxxx
    python -m openalex_trend validate   # クエリ検証
    python -m openalex_trend plan       # 推定リクエスト数・費用
    python -m openalex_trend run        # 集計 + CSV/JSON/PNG 出力
    python -m openalex_trend diagnose   # 一致論文の subfield 分布(分母の妥当性の診断)
    python -m openalex_trend sample     # 精度検証用サンプル
"""

from __future__ import annotations

import argparse
import sys

from . import diagnose, validation
from .analysis import default_trend_table
from .client import API_KEY_ENV, BudgetExceeded, OpenAlexClient, OpenAlexError
from .config import DEFAULT_CONFIG, Config, load_config
from .counts import fetch_denominators
from .dataset import add_ratios, build_metrics
from .report import plot_ratio, write_csv, write_dashboard_json, write_metrics_csv
from .sampler import sample_all, write_samples
from .works import fetch_topic_works, plan_requests


def _announce(client: OpenAlexClient, reqs: list[dict], extra: int = 0) -> None:
    """推定リクエスト数を表示し、予算を超えるなら通信前に中止する。"""
    plan = client.describe_plan(reqs, extra)
    print(plan.format())
    if plan.to_run + plan.extra_unknown > client.max_requests - client.network_requests:
        raise BudgetExceeded("推定リクエスト数が1日の予算を超える")


def cmd_plan(client: OpenAlexClient, cfg: Config, args) -> None:
    reqs, extra = plan_requests(client, cfg)  # 未取得の語句は件数取得(各1リクエスト)だけ通信する
    print(client.describe_plan(reqs, extra).format())


def cmd_run(client: OpenAlexClient, cfg: Config, args) -> None:
    reqs, extra = plan_requests(client, cfg)
    _announce(client, reqs, extra)
    if args.dry_run:
        return
    denominators = fetch_denominators(client, cfg)
    topic_works, phrase_counts = {}, {}
    for f in cfg.fields:  # 取得済みの語句はキャッシュから読むので、新しい語句の分だけ通信する
        topic_works[f.label], phrase_counts[f.label] = fetch_topic_works(client, cfg, f)
    metrics = add_ratios(cfg, build_metrics(cfg, topic_works), denominators)
    out = cfg.output_dir
    trend = default_trend_table(cfg, metrics, denominators)
    for p in (
        write_csv(trend, out),
        write_metrics_csv(metrics, out),
        write_dashboard_json(cfg, metrics, denominators, phrase_counts, out),
        plot_ratio(cfg, trend, out),
    ):
        print("出力:", p)


def cmd_validate(client: OpenAlexClient, cfg: Config, args) -> None:
    _announce(client, validation.planned_requests(cfg))
    if args.dry_run:
        return
    results = validation.validate_all(client, cfg)
    print(validation.format_report(results))
    print("出力:", validation.write_report(results, cfg.output_dir))


def cmd_diagnose(client: OpenAlexClient, cfg: Config, args) -> None:
    _announce(client, diagnose.planned_requests(cfg))
    if args.dry_run:
        return
    rows = diagnose.diagnose_all(client, cfg)
    print(diagnose.format_report(rows))
    print("出力:", diagnose.write_csv(rows, cfg.output_dir))


def cmd_sample(client: OpenAlexClient, cfg: Config, args) -> None:
    reqs, extra = plan_requests(client, cfg)
    _announce(client, reqs, extra)
    if args.dry_run:
        return
    rows = sample_all(client, cfg)
    print("出力:", write_samples(rows, cfg.output_dir / "samples"), f"({len(rows)}件)")


COMMANDS = {"plan": cmd_plan, "run": cmd_run, "validate": cmd_validate, "sample": cmd_sample, "diagnose": cmd_diagnose}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="openalex_trend")
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--dry-run", action="store_true", help="推定のみ表示して通信しない")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    client = OpenAlexClient(cfg)
    if not client.api_key:
        print(f"警告: 環境変数 {API_KEY_ENV} が未設定", file=sys.stderr)
    try:
        COMMANDS[args.command](client, cfg, args)
    except OpenAlexError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"通信 {client.network_requests} 回 / キャッシュ命中 {client.cache_hits} 回")
    return 0
