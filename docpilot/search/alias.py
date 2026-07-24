from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func

from docpilot.db.schema import TermAlias

_KOREAN_TAGS = ("NNG", "NNP")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")


def extract_pairs(text: str) -> list[tuple[str, str]]:
    """
    Extract (korean_term, latin_alias) pairs from bilingual parenthetical
    notation, e.g. "에코플라스틱(Ecoplastic)" or "Ecoplastic(에코플라스틱)".

    Pure rule-based on kiwipiepy POS tags — no LLM call. Only catches pairs
    the source text already spells out explicitly; terms without an explicit
    pairing anywhere in the document are not guessed at.
    """
    if not text:
        return []

    from docpilot.search.morpheme import _get_kiwi

    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    pairs: list[tuple[str, str]] = []

    i = 0
    n = len(tokens)
    while i < n:
        tag = tokens[i].tag

        # Pattern A: 한글(Latin)
        if tag in _KOREAN_TAGS and _is_open_paren(tokens, i + 1):
            j = i + 2
            latin_parts: list[str] = []
            while j < n and tokens[j].tag == "SL":
                latin_parts.append(tokens[j].form)
                j += 1
            if latin_parts and _is_close_paren(tokens, j):
                pairs.append((tokens[i].form, " ".join(latin_parts)))
                i = j + 1
                continue

        # Pattern B: Latin(한글)
        if tag == "SL":
            j = i
            latin_parts = []
            while j < n and tokens[j].tag == "SL":
                latin_parts.append(tokens[j].form)
                j += 1
            if _is_open_paren(tokens, j):
                k = j + 1
                korean_parts: list[str] = []
                while k < n and tokens[k].tag in _KOREAN_TAGS:
                    korean_parts.append(tokens[k].form)
                    k += 1
                if korean_parts and _is_close_paren(tokens, k):
                    pairs.append(("".join(korean_parts), " ".join(latin_parts)))
                    i = k + 1
                    continue

        i += 1

    return pairs


def _is_open_paren(tokens: list, idx: int) -> bool:
    return idx < len(tokens) and tokens[idx].tag == "SSO" and tokens[idx].form == "("


def _is_close_paren(tokens: list, idx: int) -> bool:
    return idx < len(tokens) and tokens[idx].tag == "SSC" and tokens[idx].form == ")"


def store_aliases(
    db: Any,
    pairs: list[tuple[str, str]],
    source_document_id: int | None = None,
) -> None:
    """Insert (korean_term, latin_alias) pairs into term_aliases, skipping exact duplicates."""
    for korean_term, latin_alias in pairs:
        exists = (
            db.query(TermAlias)
            .filter(
                TermAlias.korean_term == korean_term,
                TermAlias.latin_alias == latin_alias,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            TermAlias(
                korean_term=korean_term,
                latin_alias=latin_alias,
                source_document_id=source_document_id,
            )
        )
    db.flush()


def expand_query(db: Any, query: str) -> list[str]:
    """
    Return Korean terms whose alias entry's Latin form starts with a Latin
    word found in *query* (case-insensitive prefix match), so a partial
    romanized query (e.g. "eco") reaches the full aliased term
    (e.g. "에코플라스틱" via alias "Ecoplastic").
    """
    words = {w.lower() for w in _LATIN_WORD_RE.findall(query)}
    if not words:
        return []

    terms: set[str] = set()
    for word in words:
        rows = (
            db.query(TermAlias.korean_term)
            .filter(func.lower(TermAlias.latin_alias).like(f"{word}%"))
            .all()
        )
        terms.update(r[0] for r in rows)
    return sorted(terms)
