"""トピック定義(見出し語句・言い換え・除外語句)の読み書きと検証。

topics.json(リポジトリ直下)に保存する。形式:
  [{"id": "SSM", "headword": "state space model",
    "synonyms": ["state-space model"], "excludes": ["mamba"]}, ...]
検索は 見出し語句 OR 言い換え。除外語句をタイトルに含む論文は集計から外す。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .text import normalize_phrase

MAX_TOPICS = 8  # 折れ線の色を識別できる上限
MAX_PHRASES = 20  # 1トピックあたりの言い換え・除外語句それぞれの上限
MAX_LEN = 120


class TopicError(ValueError):
    """トピック定義が不正。メッセージはそのまま画面に出す。"""


def _clean_list(values, label: str) -> list[str]:
    if not isinstance(values, list):
        raise TopicError(f"{label} は配列で指定する")
    out: dict[str, str] = {}
    for v in values:
        if not isinstance(v, str):
            raise TopicError(f"{label} に文字列以外がある")
        v = " ".join(v.replace('"', "").split())
        if not v:
            continue
        if len(v) > MAX_LEN:
            raise TopicError(f"{label} が長すぎる({MAX_LEN}文字まで): {v[:20]}…")
        out.setdefault(normalize_phrase(v), v)  # 表記違いの重複は先に書いた方を残す
    if len(out) > MAX_PHRASES:
        raise TopicError(f"{label} は {MAX_PHRASES} 個まで")
    return list(out.values())


def make_id(headword: str, taken: set[str]) -> str:
    """見出し語句から ID を作る(英数字のみ。重複したら連番を付ける)。"""
    base = "".join(w[0].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", headword))[:24] or "Topic"
    tid, n = base, 2
    while tid in taken:
        tid, n = f"{base}{n}", n + 1
    return tid


def validate_topics(raw) -> list[dict]:
    """画面やファイルから来たトピック定義を検証・整形して返す。"""
    if not isinstance(raw, list):
        raise TopicError("トピックの一覧は配列で指定する")
    if not raw:
        raise TopicError("トピックは1つ以上必要")
    if len(raw) > MAX_TOPICS:
        raise TopicError(f"トピックは {MAX_TOPICS} 個まで")
    topics, taken, heads, colors = [], set(), set(), set()
    for t in raw:
        if not isinstance(t, dict):
            raise TopicError("トピックの形式が不正")
        head = " ".join(str(t.get("headword", "")).replace('"', "").split())
        if not head:
            raise TopicError("見出し語句が空のトピックがある")
        if len(head) > MAX_LEN:
            raise TopicError("見出し語句が長すぎる")
        if normalize_phrase(head) in heads:
            raise TopicError(f"見出し語句が重複している: {head}")
        heads.add(normalize_phrase(head))
        syn = [s for s in _clean_list(t.get("synonyms", []), "言い換え")
               if normalize_phrase(s) != normalize_phrase(head)]
        exc = _clean_list(t.get("excludes", []), "除外語句")
        tid = str(t.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", tid) or tid in taken:
            tid = make_id(head, taken)
        taken.add(tid)
        color = t.get("color")
        if not isinstance(color, int) or isinstance(color, bool) or not 0 <= color < MAX_TOPICS or color in colors:
            color = None  # 未指定・重複は後で空いている色を割り当てる
        else:
            colors.add(color)
        topics.append({"id": tid, "headword": head, "synonyms": syn, "excludes": exc, "color": color})
    # 色はトピックに固定する(追加・削除で他のトピックの色が変わらないように)
    free = (c for c in range(MAX_TOPICS) if c not in colors)
    for t in topics:
        if t["color"] is None:
            t["color"] = next(free)
    return topics


def load_topics(path: Path) -> list[dict]:
    return validate_topics(json.loads(Path(path).read_text(encoding="utf-8")))


def save_topics(path: Path, topics: list[dict]) -> None:
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(topics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
