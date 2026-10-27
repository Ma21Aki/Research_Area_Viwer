"""コマンドライン: plan / run / validate / sample。

使い方(backend/ で実行):
    export OPENALEX_API_KEY=xxxx
    python -m openalex_trend validate   # クエリ検証
    python -m openalex_trend plan       # 推定リクエスト数・費用
    python -m openalex_trend run        # 集計 + CSV/JSON/PNG 出力
    python -m openalex_trend sample     # 精度検証用サンプル
"""

from __future__ import annotations

import argparse
import sys

from . import validation
from .analysis import build_trend_table
from .client import API_KEY_ENV, BudgetExceeded, OpenAlexClient, OpenAlexError
from .config import DEFAULT_CONFIG, Config, load_config
from .counts import fetch_all, plan_requests
from .report import plot_ratio, write_csv, write_summary_json
from .sampler import sample_all, write_samples


def _announce(client: OpenAlexClient, reqs: list[dict], extra: int = 0) -> None:
    """推定リクエスト数を表示し、予算を超えるなら通信前に中止する。"""
    plan = client.describe_plan(reqs, extra)
    print(plan.format())
    if plan.to_run + plan.extra_unknown > client.max_requests - client.network_requests:
        raise BudgetExceeded("推定リクエスト数が1日の予算を超える")


def cmd_plan(client: OpenAlexClient, cfg: Config, args) -> None:
    reqs, extra = plan_requests(client, cfg)
    print(client.describe_plan(reqs, extra).format())


def cmd_run(client: OpenAlexClient, cfg: Config, args) -> None:
    reqs, extra = plan_requests(client, cfg)
    _announce(client, reqs, extra)
    if args.dry_run:
        return
    denominator, counts = fetch_all(client, cfg)
    table = build_trend_table(cfg, denominator, counts)
    out = cfg.output_dir
    for p in (write_csv(table, out), write_summary_json(cfg, table, out), plot_ratio(cfg, table, out)):
        print("出力:", p)


def cmd_validate(client: OpenAlexClient, cfg: Config, args) -> None:
    _announce(client, validation.planned_requests(cfg))
    if args.dry_run:
        return
    results = validation.validate_all(client, cfg)
    print(validation.format_report(results))
    print("出力:", validation.write_report(results, cfg.output_dir))


def cmd_sample(client: OpenAlexClient, cfg: Config, args) -> None:
    if cfg.query_mode == "or":
        _announce(client, [], extra=len(cfg.fields))
    if args.dry_run:
        return
    rows = sample_all(client, cfg)
    print("出力:", write_samples(rows, cfg.output_dir / "samples"), f"({len(rows)}件)")


COMMANDS = {"plan": cmd_plan, "run": cmd_run, "validate": cmd_validate, "sample": cmd_sample}


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
