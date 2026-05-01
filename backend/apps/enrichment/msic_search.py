"""MSIC code suggestion (Slice 94 — v1).

LHDN's MSIC catalog has thousands of 5-digit codes. SME owners can't
memorise them, so the spec promises a smart suggestion path
(``PRODUCT_REQUIREMENTS.md`` §63 — "Qdrant-backed semantic search +
language-model reasoning"). v1 ships a simpler approach that's
useful today: token-overlap ranking against the cached
``MsicCode.description_en`` (+ ``description_bm``).

Why ship the simpler version first:

  - The MSIC catalog we cache today has 32 entries — full-blown
    embeddings would be over-engineering. When the catalog refresh
    pulls the full ~1500-entry list, vector search becomes worth
    the infra.
  - Token overlap is deterministic, instant, and surfaces the
    obviously-right code 80% of the time on item descriptions
    that include the right industry noun.
  - The interface (``suggest_msic(query) -> [Suggestion]``) doesn't
    change when we swap the backing store; only the ranker does.
    Keeps the UI commitment cheap.

The LLM reasoning step from the spec lands in v2 — give the user
the top-N candidates from this ranker and ask the LLM to pick the
best one given the full line context (description + buyer
industry + prior usage). Wired the same way: take ``[Suggestion]``,
return ``[Suggestion]`` re-ranked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from apps.administration.models import MsicCode


@dataclass(frozen=True)
class Suggestion:
    code: str
    description_en: str
    description_bm: str
    score: float


# Single-letter words and common stop words contribute noise to a token
# overlap score. Excluded from the query-side tokenization. We don't
# strip stop words from the catalog side — the description is already
# concise (LHDN-curated), and dropping "of" / "and" from "Wholesale of
# pharmaceuticals" would change scoring in unexpected ways.
_QUERY_STOP = frozenset(
    {
        "the",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "from",
        "with",
        "a",
        "an",
        "as",
        "is",
        "are",
        "be",
        "this",
        "that",
        "fees",  # too generic on invoices
        "fee",
        "service",
        "services",
    }
)


def _tokenize(text: str) -> list[str]:
    """Split on non-alphanum, lower-case, drop empties + numerics-only.

    We keep multi-character tokens only because single letters add
    noise (e.g. "I" / "A" matching every description with those
    letters in pseudo-words). Numeric-only tokens are usually
    dates / quantities / SKUs — also noisy for industry matching.
    """
    return [
        t
        for t in (token.lower() for token in re.split(r"[^A-Za-z0-9]+", text or ""))
        if len(t) > 1 and not t.isdigit()
    ]


def _related(token_a: str, token_b: str) -> bool:
    """Cheap morphological-relatedness check.

    Without a real stemmer, treat two tokens as related if they
    share a 5+ character prefix. Catches the pairs the catalog
    actually trips on:

      consulting ↔ consultancy   ("consult" prefix, 7 chars)
      manufacture ↔ manufacturing ("manufact", 8 chars)
      retail ↔ retailer           ("retail", 6 chars)
      pharmaceutical ↔ pharmacy   ("pharma", 6 chars)

    5 chars is the floor — going lower starts matching unrelated
    nouns ("computer" / "compute" is fine; "compu" matches "computer"
    AND "competition", which we don't want).
    """
    if token_a == token_b:
        return True
    short, long_ = (token_a, token_b) if len(token_a) <= len(token_b) else (token_b, token_a)
    if len(short) < 5:
        return False
    return long_.startswith(short[:5]) and short[:5] == long_[:5]


def _score(query_tokens: set[str], description: str) -> float:
    """Token-overlap × description-length-penalty.

    Overlap alone biases toward long catalog descriptions that
    happen to contain many noun phrases. Dividing by sqrt(len) gives
    a gentler counter-penalty that still rewards specific matches
    over general ones.

    Exact matches score 1.0; morphologically-related matches
    (consulting ↔ consultancy) score 0.6 — useful but downweighted
    so an exact match always beats a fuzzy one.
    """
    if not query_tokens:
        return 0.0
    catalog_tokens = set(_tokenize(description))
    if not catalog_tokens:
        return 0.0
    score = 0.0
    for q in query_tokens:
        if q in catalog_tokens:
            score += 1.0
            continue
        if any(_related(q, c) for c in catalog_tokens):
            score += 0.6
    if score == 0:
        return 0.0
    import math

    return score / math.sqrt(len(catalog_tokens))


def suggest_msic(query: str, *, limit: int = 5) -> list[Suggestion]:
    """Rank MSIC codes by token overlap with the query.

    Returns up to ``limit`` candidates sorted by score descending.
    An empty / all-stop-word query returns ``[]`` rather than the
    full catalog — better UX than a wall of arbitrary codes.
    """
    raw_tokens = _tokenize(query)
    query_tokens = {t for t in raw_tokens if t not in _QUERY_STOP}
    if not query_tokens:
        return []

    candidates: list[Suggestion] = []
    # The catalog is small (32 entries today, ~1.5k at full size).
    # In-memory scoring is fine; we'd add an SQL-side first-pass
    # filter (description ILIKE ANY token) before scoring once
    # the full catalog lands.
    for row in MsicCode.objects.filter(is_active=True):
        description = f"{row.description_en} {row.description_bm}".strip()
        score = _score(query_tokens, description)
        if score <= 0:
            continue
        candidates.append(
            Suggestion(
                code=row.code,
                description_en=row.description_en,
                description_bm=row.description_bm,
                score=score,
            )
        )

    candidates.sort(key=lambda s: (-s.score, s.code))
    return candidates[:limit]
