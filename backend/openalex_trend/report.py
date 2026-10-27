"""出力: CSV / フロントエンド用 JSON / 折れ線グラフ(PNG)。

フロントエンドとの接点は outputs/ 配下のファイルだけにする。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面のない環境(Actions など)でも描画できるようにする
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .config import Config  # noqa: E402
from .dataset import METRIC_COLUMNS, nullable  # noqa: E402
from .queries import LEVELS, normalize_phrase  # noqa: E402

# 検証済みの categorical パレット(薄い黄・緑などはコントラスト不足のため、
# 凡例・線端の直接ラベル・マーカー形状でも系列を識別できるようにしている)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "h"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"

CSV_NAME = "title_trend.csv"
JSON_NAME = "dashboard.json"
METRICS_CSV_NAME = "topic_metrics.csv"
PNG_NAME = "title_trend_ratio.png"


def write_csv(table: pd.DataFrame, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / CSV_NAME
    table.to_csv(path, index=False, float_format="%.8g")
    return path


def write_metrics_csv(metrics: pd.DataFrame, out_dir: Path) -> Path:
    """全指標を縦持ちで出力(分母の3水準・出現率・被引用の指標)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / METRICS_CSV_NAME
    metrics.to_csv(path, index=False, float_format="%.8g")
    return path


def write_dashboard_json(
    cfg: Config,
    metrics: pd.DataFrame,
    denominators: dict[str, pd.Series],
    phrase_counts: dict[str, dict[str, int]],
    out_dir: Path,
) -> Path:
    """フロントエンド用 JSON。出現率・移動平均は画面側で計算するので、素の件数と指標だけを渡す。"""
    years = list(cfg.years)
    generated = datetime.now(timezone.utc)
    names = {"all": "全論文", "field": cfg.oa_field_name, "subfield": cfg.subfield_name}
    topics = []
    for f in cfg.fields:
        t = metrics[metrics["field"] == f.label].set_index("year").reindex(years)
        counts = phrase_counts.get(f.label, {})
        uniq = {normalize_phrase(p): p for p in reversed(f.phrases)}  # 先に書いた語句が代表
        topics.append(
            {
                "label": f.label,
                "display_name": f.display_name,
                "phrases": [
                    {
                        "phrase": p,
                        "count": counts.get(uniq[normalize_phrase(p)], 0),
                        "merged_into": None if uniq[normalize_phrase(p)] == p else uniq[normalize_phrase(p)],
                    }
                    for p in f.phrases
                ],
                "series": {c: nullable(t[c]) for c in METRIC_COLUMNS},
            }
        )
    doc = {
        "generated_at": generated.isoformat(timespec="seconds"),
        "partial_year": generated.year if generated.year in years else None,
        "work_type": cfg.work_type,
        "default_denominator": cfg.default_denominator,
        "years": years,
        "denominators": {
            lv: {
                "name": names[lv],
                "series": [int(denominators[lv].get(y, 0)) for y in years],
            }
            for lv in LEVELS
        },
        "topics": topics,
    }
    path = out_dir / JSON_NAME
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def plot_ratio(cfg: Config, table: pd.DataFrame, out_dir: Path) -> Path:
    """比率の折れ線。細線=年次の比率、太線=3年移動平均。線端に分野名を直接ラベルする。"""
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ends = []
    for i, f in enumerate(cfg.fields):
        color = SERIES_COLORS[i % len(SERIES_COLORS)]
        marker = SERIES_MARKERS[i % len(SERIES_MARKERS)]
        t = table[table["field"] == f.label].set_index("year")
        ax.plot(t.index, t["ratio"], color=color, lw=1, alpha=0.45,
                marker=marker, ms=3.5, markeredgecolor=SURFACE, markeredgewidth=0.6)
        ax.plot(t.index, t["ratio_ma3"], color=color, lw=2.2, label=f.display_name)
        last = t["ratio_ma3"].dropna()
        if not last.empty:
            ends.append((last.iloc[-1], last.index[-1], f.display_name))
    # 線端ラベルは値の昇順に並べて最小間隔を空け、重なりを避ける
    ymax = max((e[0] for e in ends), default=1) or 1
    gap, prev = ymax * 0.045, None
    for y, x, name in sorted(ends):
        ty = y if prev is None else max(y, prev + gap)
        ax.annotate(name, (x, y), xytext=(x + 0.6, ty), fontsize=8,
                    color=INK_SECONDARY, va="center",
                    arrowprops=dict(arrowstyle="-", color=GRID, lw=0.8))
        prev = ty
    ax.set_xlim(cfg.year_from, cfg.year_to + 7)
    ax.set_ylim(bottom=0)
    ax.set_xticks(range(cfg.year_from - cfg.year_from % 5, cfg.year_to + 1, 5))  # ラベル用の余白に目盛りを出さない
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1%}"))
    base = {"all": "all works", "field": cfg.oa_field_name, "subfield": cfg.subfield_name}
    ax.set_ylabel(f"Share of titles among {base[cfg.default_denominator]}",
                  color=INK_SECONDARY, fontsize=9)
    ax.set_title("Title occurrence rate by research field (OpenAlex)",
                 color=INK, fontsize=11, loc="left")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.tick_params(colors=INK_SECONDARY, labelsize=8, length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    legend = ax.legend(loc="upper left", frameon=False, fontsize=8,
                       title="thick: 3-yr moving avg / thin: yearly", title_fontsize=7)
    legend.get_title().set_color(INK_SECONDARY)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    fig.tight_layout()
    path = out_dir / PNG_NAME
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path
