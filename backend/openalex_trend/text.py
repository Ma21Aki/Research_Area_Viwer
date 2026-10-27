"""語句・タイトルの正規化と照合(通信しない純粋関数)。"""

from __future__ import annotations

import re


def normalize_phrase(text: str) -> str:
    """ハイフン・大小・空白の違いを畳む(OpenAlex 側でも同一視されるため重複取得を避ける)。"""
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def phrase_pattern(phrase: str) -> re.Pattern:
    """除外語句の照合パターン。単語単位で一致させ、複数形(s / es)も含める。

    例: "transformer" は "Transformers" に一致し、"nn" は "annual" に一致しない。
    """
    words = normalize_phrase(phrase)
    return re.compile(r"(?<![a-z0-9])" + re.escape(words) + r"(?:e?s)?(?![a-z0-9])")


def title_matches(title: str, pattern: re.Pattern) -> bool:
    return bool(pattern.search(normalize_phrase(title)))
