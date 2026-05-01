"""Bank Negara Malaysia exchange-rate fetcher (Slice 96).

BNM publishes daily reference rates at api.bnm.gov.my/public/exchange-rate.
The endpoint is unauthenticated for the public daily-rates path; we hit
it on a daily celery beat schedule, upsert each (date, currency) pair
into ``BnmExchangeRate``, and call it a day. The actual MYR-equivalent
calculation lives in ``apps.enrichment.currency``; this module is only
the cache + refresh.

Why we cache instead of calling per-invoice:

  - BNM's API is unauthenticated but rate-limited. A single
    refresh per day is plenty.
  - Validation runs hot (every Save on the review page now,
    Slice 91). Hitting BNM on every validation would be a
    latency cliff.
  - Audit: a row in ``bnm_exchange_rate`` is the durable evidence
    of WHICH rate we used for an invoice's MYR equivalent. The
    LHDN audit reader can join Invoice.issue_date back to the
    cached rate.

Soft-fail behaviour: if BNM is unreachable / returns malformed JSON,
we log + return without raising so the rest of the celery beat tick
isn't poisoned. The cached rates from the previous successful fetch
remain authoritative until the next successful fetch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import timedelta
from decimal import Decimal

import httpx

from .models import BnmExchangeRate

logger = logging.getLogger(__name__)


# BNM's public endpoint. No authentication required for this path.
# The "session" path (1130 / 1200 / 1700) is BNM's intra-day
# fixing — we use the latest published session.
_BNM_DAILY_URL = "https://api.bnm.gov.my/public/exchange-rate"

# Currencies we care about for Malaysian SME invoicing. Most foreign-
# currency invoicing in Malaysia is USD / SGD / EUR / GBP / JPY / CNY.
# BNM publishes more, but only fetch what we need (saves the row count).
_TRACKED_CURRENCIES = frozenset({"USD", "SGD", "EUR", "GBP", "JPY", "CNY", "AUD", "HKD", "THB"})


@dataclass(frozen=True)
class FetchSummary:
    fetched: int
    upserted: int
    unchanged: int
    failed_reason: str = ""


def fetch_and_cache(*, http: httpx.Client | None = None) -> FetchSummary:
    """Fetch BNM's daily rates + upsert into ``BnmExchangeRate``.

    ``http`` is injectable for tests. In production we construct a
    one-off ``httpx.Client`` with a short timeout; BNM's endpoint
    typically responds in <1s and we don't want a slow day to
    block the celery beat tick.
    """
    client = http or httpx.Client(
        timeout=10.0,
        headers={"Accept": "application/vnd.BNM.API.v1+json"},
    )
    try:
        response = client.get(_BNM_DAILY_URL)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("administration.bnm_rates.fetch_failed: %s", exc)
        return FetchSummary(fetched=0, upserted=0, unchanged=0, failed_reason=str(exc))

    rows = _parse_payload(payload)
    if not rows:
        return FetchSummary(
            fetched=0, upserted=0, unchanged=0, failed_reason="empty / unrecognised payload"
        )

    upserted = 0
    unchanged = 0
    for row in rows:
        obj, created = BnmExchangeRate.objects.update_or_create(
            rate_date=row.rate_date,
            currency_code=row.currency_code,
            defaults={
                "buying_rate": row.buying_rate,
                "selling_rate": row.selling_rate,
                "middle_rate": row.middle_rate,
            },
        )
        if created or _changed(obj, row):
            upserted += 1
        else:
            unchanged += 1
    return FetchSummary(fetched=len(rows), upserted=upserted, unchanged=unchanged)


@dataclass(frozen=True)
class _ParsedRow:
    rate_date: date_cls
    currency_code: str
    buying_rate: Decimal | None
    selling_rate: Decimal | None
    middle_rate: Decimal


def _parse_payload(payload: dict) -> list[_ParsedRow]:
    """Pull the rate rows out of BNM's wire format.

    Two shapes BNM has used in practice:

      {"data": [{"currency_code": "USD", "rate": {...}, ...}], "meta": {...}}
      {"data": {"currency_code": "USD", ...}}

    We accept either. Currencies outside ``_TRACKED_CURRENCIES`` are
    skipped — they'd add noise + grow the table without serving any
    customer.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if data is None:
        return []
    items = data if isinstance(data, list) else [data]

    out: list[_ParsedRow] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        currency = (item.get("currency_code") or "").upper()
        if currency not in _TRACKED_CURRENCIES:
            continue
        rate_block = item.get("rate") if isinstance(item.get("rate"), dict) else item
        try:
            middle = _to_decimal(rate_block.get("middle_rate"))
        except (TypeError, ValueError):
            continue
        if middle is None:
            continue
        try:
            row_date = date_cls.fromisoformat(item.get("date") or rate_block.get("date") or "")
        except ValueError:
            row_date = date_cls.today()
        out.append(
            _ParsedRow(
                rate_date=row_date,
                currency_code=currency,
                buying_rate=_to_decimal(rate_block.get("buying_rate")),
                selling_rate=_to_decimal(rate_block.get("selling_rate")),
                middle_rate=middle,
            )
        )
    return out


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _changed(obj: BnmExchangeRate, row: _ParsedRow) -> bool:
    return (
        obj.buying_rate != row.buying_rate
        or obj.selling_rate != row.selling_rate
        or obj.middle_rate != row.middle_rate
    )


def lookup_rate(*, currency_code: str, on_or_before: date_cls) -> BnmExchangeRate | None:
    """Return the most recent rate for ``currency_code`` at or before ``on_or_before``.

    LHDN's spec asks for the rate on the invoice's issue date. BNM
    doesn't publish on weekends / public holidays, so we walk
    backwards up to 14 days for the nearest prior business-day rate.
    Returning None means "no rate available" — caller decides
    whether to surface a warning vs proceed without MYR equivalent.
    """
    if currency_code.upper() == "MYR":
        return None
    cutoff = on_or_before - timedelta(days=14)
    return (
        BnmExchangeRate.objects.filter(
            currency_code=currency_code.upper(),
            rate_date__lte=on_or_before,
            rate_date__gte=cutoff,
        )
        .order_by("-rate_date")
        .first()
    )
