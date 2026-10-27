"""テスト用のOpenAlex偽サーバー。requests.Session の get だけを真似る。

小さなコーパスに対して filter / search.title / group_by / cursor / sample を再現する。
mode で「検索が壊れている」状況も作れる(クエリ検証のテスト用)。
"""

from __future__ import annotations

import random
import re

import requests

TARGET_SUBFIELD = "subfields/2613"
OTHER_SUBFIELD = "subfields/9999"
SUBFIELD_NAMES = {TARGET_SUBFIELD: "Statistics and Probability", OTHER_SUBFIELD: "Control and Systems Engineering"}
FIELD_OF = {TARGET_SUBFIELD: "fields/26", OTHER_SUBFIELD: "fields/22"}
FIELD_NAMES = {"fields/26": "Mathematics", "fields/22": "Engineering"}


def make_corpus() -> list[dict]:
    """決め打ちの小さなコーパス(期待値を手計算できる大きさ)。"""
    works, n = [], 0

    def add(title, year, subfield=TARGET_SUBFIELD, wtype="article"):
        nonlocal n
        n += 1
        field = FIELD_OF[subfield]
        works.append(
            {
                "id": f"https://openalex.org/W{1000 + n}",
                "title": title,
                "publication_year": year,
                "type": wtype,
                "cited_by_count": (n * 3) % 11,
                "counts_by_year": [
                    {"year": 2022, "cited_by_count": n % 4},
                    {"year": 2023, "cited_by_count": (n + 1) % 3},
                ],
                "fwci": None if n % 10 == 0 else ((n % 7) + 1) / 4,
                "citation_normalized_percentile": {"value": 0.5, "is_in_top_10_percent": n % 5 == 0},
                "primary_topic": {
                    "display_name": f"Topic {n % 3}",
                    "subfield": {"id": f"https://openalex.org/{subfield}"},
                    "field": {"id": f"https://openalex.org/{field}"},
                },
            }
        )

    for i in range(6):  # state space model: 2020 x2, 2021 x2, 2022 x2
        add(f"A state space model for series {i}", 2020 + i // 2)
    for i in range(3):  # ハイフン表記(正規化で上と同じフレーズ扱い)
        add(f"State-space model estimation {i}", 2022)
    for i in range(4):  # dynamic linear model: 2021 x2, 2023 x2
        add(f"Dynamic linear model of data {i}", 2021 if i < 2 else 2023)
    for i in range(3):  # hierarchical Bayesian
        add(f"Hierarchical Bayesian analysis {i}", 2022)
    add("A model of state and space", 2021)  # 単語ANDには一致するがフレーズには一致しない
    for year, k in ((2020, 20), (2021, 20), (2022, 30), (2023, 30)):
        for i in range(k):
            add(f"Regression for sample {year}-{i}", year)
    add("State space model in economics", 2021, OTHER_SUBFIELD)  # 別 subfield(別 field)
    add("State space model of the past", 1980)  # 対象年の範囲外
    return works


def short(url: str) -> str:
    return url.split("openalex.org/")[-1]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeOpenAlex:
    def __init__(self, corpus=None, search_mode="correct", fail_with=()):
        self.corpus = corpus if corpus is not None else make_corpus()
        self.search_mode = search_mode  # correct / ignored / or_literal
        self.fail_with = list(fail_with)  # 先頭から順に返す異常ステータス
        self.calls: list[dict] = []

    # ---- requests.Session 互換 ----------------------------------------
    def get(self, url, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append(params)
        if self.fail_with:
            item = self.fail_with.pop(0)
            if isinstance(item, Exception):
                raise item
            status, headers = item if isinstance(item, tuple) else (item, {})
            return FakeResponse(status, None, headers, text="error")
        return FakeResponse(200, self._handle(params))

    # ---- 検索の意味論 ---------------------------------------------------
    def _term_match(self, title: str, term: str) -> bool:
        t = _norm(title)
        if term.startswith('"') and term.endswith('"'):
            return _norm(term[1:-1]) in t  # フレーズ
        return all(w in t.split() for w in _norm(term).split())  # 単語のAND

    def _search(self, title: str, query: str) -> bool:
        if self.search_mode == "ignored":
            return True
        if self.search_mode == "or_literal":
            return self._term_match(title, query)  # " OR " ごと1つの語句として探す
        return any(self._term_match(title, term) for term in query.split(" OR "))

    def _filter(self, expr: str) -> list[dict]:
        works = self.corpus
        for part in expr.split(","):
            key, _, val = part.partition(":")
            if key == "primary_topic.subfield.id":
                works = [w for w in works if short(w["primary_topic"]["subfield"]["id"]) == val]
            elif key == "primary_topic.field.id":
                works = [w for w in works if short(w["primary_topic"]["field"]["id"]) == val]
            elif key == "type":
                works = [w for w in works if w["type"] == val]
            elif key == "publication_year":
                lo, _, hi = val.partition("-")
                works = [w for w in works if int(lo) <= w["publication_year"] <= int(hi or lo)]
            elif key == "openalex":
                ids = {f"https://openalex.org/{x}" for x in val.split("|")}
                works = [w for w in works if w["id"] in ids]
        return works

    def _handle(self, p: dict) -> dict:
        works = self._filter(p.get("filter", ""))
        if "search.title" in p:
            works = [w for w in works if self._search(w["title"], p["search.title"])]
        if "group_by" in p:
            return self._group_by(works, p["group_by"])
        per_page = int(p.get("per_page", 25))
        meta = {"count": len(works)}
        if "sample" in p:
            ids = sorted(works, key=lambda w: w["id"])
            works = random.Random(int(p.get("seed", 0))).sample(ids, min(int(p["sample"]), len(ids)))
            page = int(p.get("page", 1))
            return {"meta": meta, "results": [self._select(w, p) for w in works[(page - 1) * per_page : page * per_page]]}
        if "cursor" in p:
            offset = 0 if p["cursor"] == "*" else int(p["cursor"])
            chunk = works[offset : offset + per_page]
            more = offset + per_page < len(works)
            meta["next_cursor"] = str(offset + per_page) if more else None
            return {"meta": meta, "results": [self._select(w, p) for w in chunk]}
        return {"meta": meta, "results": [self._select(w, p) for w in works[:per_page]]}

    @staticmethod
    def _group_by(works: list[dict], key: str) -> dict:
        def keyof(w):
            if key == "publication_year":
                return str(w["publication_year"]), str(w["publication_year"])
            sub = short(w["primary_topic"]["subfield"]["id"])
            if key == "primary_topic.subfield.id":
                return f"https://openalex.org/{sub}", SUBFIELD_NAMES[sub]
            if key == "primary_topic.field.id":
                f = FIELD_OF[sub]
                return f"https://openalex.org/{f}", FIELD_NAMES[f]
            raise ValueError(key)

        counts: dict[tuple, int] = {}
        for w in works:
            counts[keyof(w)] = counts.get(keyof(w), 0) + 1
        groups = [
            {"key": k, "key_display_name": name, "count": c}
            for (k, name), c in sorted(counts.items())
        ]
        return {"meta": {"count": len(groups)}, "group_by": groups}

    @staticmethod
    def _select(w: dict, p: dict) -> dict:
        keys = p.get("select", "id,title,publication_year,primary_topic").split(",")
        return {k: w[k] for k in keys if k in w}


def connection_error(secret: str) -> requests.ConnectionError:
    """URL(APIキー入り)を含む通信エラー。キーが漏れないことの確認用。"""
    return requests.ConnectionError(f"HTTPSConnectionPool: /works?api_key={secret}")
