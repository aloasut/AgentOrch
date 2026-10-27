#!/usr/bin/env python3
"""Vendor-neutral model-evidence snapshots (#122, S3).

Design contract: ``docs/design/agent-role-discovery-and-model-selection.md``
§6. The objects here describe **what one source said, when, and with which
limitations**. They are vendor-neutral on purpose: a second source (or a local
benchmark) can fill the same fields without changing the role selector.

Three rules are structural:

1. **Missing is UNKNOWN, not zero.** Every optional field is ``None`` (or an
   empty tuple only when "none observed" is a real observation) and
   :meth:`as_dict` renders it as ``'UNKNOWN'``. ``0`` means a measured zero.
2. **Freshness is explicit.** A snapshot carries the time it was fetched and a
   ``FRESH`` / ``STALE`` / ``UNKNOWN`` class. A cached batch never claims to be
   live; an expired batch is ``STALE_CACHE`` and its models are ``STALE``.
3. **A fetch records its outcome.** Success, cache, stale cache, rate limit,
   authentication failure, tier restriction, schema change, timeout and an
   unparseable body are different statuses. Treating them as one "no data"
   would let a paywall look like a missing model capability.

Standard library only; no network and no filesystem access in this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from ..runtime_adapter import RuntimeAdapterError, parse_timestamp

__all__ = [
    'UNKNOWN',
    'PRICE_UNIT',
    'FRESHNESS_VALUES',
    'FRESHNESS_FRESH',
    'FRESHNESS_STALE',
    'FRESHNESS_UNKNOWN',
    'FETCH_STATUSES',
    'FETCH_LIVE_STATUSES',
    'FETCH_USABLE_STATUSES',
    'DEFAULT_MAX_AGE_SECONDS',
    'SnapshotError',
    'ModelEvaluation',
    'ModelPricing',
    'ModelPerformance',
    'ModelSnapshot',
    'FetchRecord',
    'SnapshotBatch',
    'CacheEntry',
    'CacheHit',
    'SnapshotCache',
    'freshness_for_age',
    'age_seconds',
    'utc_timestamp',
]

UNKNOWN = 'UNKNOWN'
PRICE_UNIT = 'USD per 1M tokens'

FRESHNESS_FRESH = 'FRESH'
FRESHNESS_STALE = 'STALE'
FRESHNESS_UNKNOWN = 'UNKNOWN'
FRESHNESS_VALUES = (FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_UNKNOWN)

# One status per fetch outcome. They deliberately do not collapse into a single
# "unavailable": a 403 from a subscription tier is not a missing capability, and
# a 429 is not an authentication problem.
FETCH_OK = 'OK'
FETCH_CACHED = 'CACHED'
FETCH_STALE_CACHE = 'STALE_CACHE'
FETCH_NO_CREDENTIAL = 'NO_CREDENTIAL'
FETCH_AUTH_FAILED = 'AUTH_FAILED'
FETCH_TIER_RESTRICTED = 'TIER_RESTRICTED'
FETCH_RATE_LIMITED = 'RATE_LIMITED'
FETCH_TIMEOUT = 'TIMEOUT'
FETCH_NETWORK_ERROR = 'NETWORK_ERROR'
FETCH_SERVER_ERROR = 'SERVER_ERROR'
FETCH_HTTP_ERROR = 'HTTP_ERROR'
FETCH_SCHEMA_CHANGED = 'SCHEMA_CHANGED'
FETCH_UNPARSEABLE = 'UNPARSEABLE'

FETCH_STATUSES = (
    FETCH_OK, FETCH_CACHED, FETCH_STALE_CACHE, FETCH_NO_CREDENTIAL,
    FETCH_AUTH_FAILED, FETCH_TIER_RESTRICTED, FETCH_RATE_LIMITED,
    FETCH_TIMEOUT, FETCH_NETWORK_ERROR, FETCH_SERVER_ERROR, FETCH_HTTP_ERROR,
    FETCH_SCHEMA_CHANGED, FETCH_UNPARSEABLE,
)
# Only a successful current read may be described as live.
FETCH_LIVE_STATUSES = (FETCH_OK,)
# Fresh cache is usable evidence; an expired cache is shown but not ranked.
FETCH_USABLE_STATUSES = (FETCH_OK, FETCH_CACHED)

DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


class SnapshotError(ValueError):
    """A snapshot or fetch record cannot be constructed as declared."""


def utc_timestamp(value=None):
    """Return ``YYYY-MM-DDTHH:MM:SSZ`` for *value*, defaulting to now (UTC)."""
    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone.utc)
    else:
        return utc_timestamp(parse_timestamp(str(value)))
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def age_seconds(stored_at, now=None):
    """Age of *stored_at* in seconds; ``None`` when it cannot be parsed."""
    try:
        observed = parse_timestamp(stored_at)
        current = parse_timestamp(utc_timestamp(now))
    except RuntimeAdapterError:
        return None
    return max(0.0, (current - observed).total_seconds())


def freshness_for_age(seconds, max_age_seconds=DEFAULT_MAX_AGE_SECONDS):
    """Freshness class of an observation of *seconds* age."""
    if seconds is None:
        return FRESHNESS_UNKNOWN
    if max_age_seconds is None or seconds <= max_age_seconds:
        return FRESHNESS_FRESH
    return FRESHNESS_STALE


def _number(value, *, field_name, allow_negative=False):
    """Return a finite float or ``None``; reject strings and bools."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SnapshotError(
            f'{field_name} must be a number or null, got {type(value).__name__}')
    number = float(value)
    if not math.isfinite(number):
        raise SnapshotError(f'{field_name} must be finite, got {value!r}')
    if number < 0 and not allow_negative:
        raise SnapshotError(f'{field_name} must not be negative, got {value!r}')
    return number


@dataclass(frozen=True)
class ModelEvaluation:
    """One published benchmark / index value, with its unit and version.

    ``value is None`` means the source did not publish this evaluation (or
    published ``null``); it is never coerced to ``0``. ``index_version`` is only
    set when the source publishes one, and a value from another index version is
    not silently compared with this one.
    """

    name: str
    value: float | None = None
    unit: str = UNKNOWN
    index_version: str | None = None
    scope: str = ''
    note: str = ''

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise SnapshotError('an evaluation needs a non-empty name')
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise SnapshotError(f'{self.name}: a unit must be stated or UNKNOWN')
        if self.value is not None:
            # Composite indices may legitimately be negative (AA-Omniscience).
            _number(self.value, field_name=self.name, allow_negative=True)
        if self.index_version is not None and (
                not isinstance(self.index_version, str)
                or not self.index_version.strip()):
            raise SnapshotError(
                f'{self.name}: index_version must be None or a non-empty string')

    @property
    def known(self):
        return self.value is not None

    def as_dict(self):
        return {
            'name': self.name,
            'value': self.value if self.value is not None else UNKNOWN,
            'unit': self.unit,
            'index_version': (self.index_version
                              if self.index_version is not None else UNKNOWN),
            'scope': self.scope,
            'note': self.note,
        }


@dataclass(frozen=True)
class ModelPricing:
    """Token pricing in one explicit unit; absent fields stay UNKNOWN."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    blended_3_to_1_per_mtok: float | None = None
    unit: str = PRICE_UNIT

    def __post_init__(self):
        for name in ('input_per_mtok', 'output_per_mtok', 'cache_read_per_mtok',
                     'cache_write_per_mtok', 'blended_3_to_1_per_mtok'):
            _number(getattr(self, name), field_name=name)
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise SnapshotError('pricing needs an explicit unit')

    @property
    def known(self):
        return any(getattr(self, name) is not None for name in (
            'input_per_mtok', 'output_per_mtok', 'cache_read_per_mtok',
            'cache_write_per_mtok', 'blended_3_to_1_per_mtok'))

    def as_dict(self):
        payload = {
            name: (getattr(self, name) if getattr(self, name) is not None
                   else UNKNOWN)
            for name in ('input_per_mtok', 'output_per_mtok',
                         'cache_read_per_mtok', 'cache_write_per_mtok',
                         'blended_3_to_1_per_mtok')
        }
        payload['unit'] = self.unit
        return payload


@dataclass(frozen=True)
class ModelPerformance:
    """Latency / throughput, each in its stated unit; missing stays UNKNOWN."""

    output_tokens_per_second: float | None = None
    time_to_first_token_seconds: float | None = None
    time_to_first_answer_token_seconds: float | None = None
    end_to_end_response_time_seconds: float | None = None

    def __post_init__(self):
        for name in ('output_tokens_per_second', 'time_to_first_token_seconds',
                     'time_to_first_answer_token_seconds',
                     'end_to_end_response_time_seconds'):
            _number(getattr(self, name), field_name=name)

    @property
    def known(self):
        return any(getattr(self, name) is not None for name in (
            'output_tokens_per_second', 'time_to_first_token_seconds',
            'time_to_first_answer_token_seconds',
            'end_to_end_response_time_seconds'))

    def as_dict(self):
        return {
            name: (getattr(self, name) if getattr(self, name) is not None
                   else UNKNOWN)
            for name in ('output_tokens_per_second',
                         'time_to_first_token_seconds',
                         'time_to_first_answer_token_seconds',
                         'end_to_end_response_time_seconds')
        }


@dataclass(frozen=True)
class ModelSnapshot:
    """One model as reported by one source at one time.

    ``canonical_id`` is the source's stable identifier (for Artificial Analysis
    it is the documented ``id``, not a display name). ``model_family`` is only
    set when the source publishes a family; otherwise it stays ``None`` and the
    selector reports ``UNKNOWN`` rather than inferring a family from a name.
    """

    canonical_id: str
    name: str
    slug: str
    source_id: str
    source_url: str
    fetched_at: str
    creator_id: str | None = None
    creator_name: str | None = None
    model_family: str | None = None
    modalities: tuple[str, ...] | None = None
    context_tokens: int | None = None
    reasoning_model: bool | None = None
    release_date: str | None = None
    evaluations: tuple[ModelEvaluation, ...] = ()
    pricing: ModelPricing | None = None
    performance: ModelPerformance | None = None
    freshness: str = FRESHNESS_UNKNOWN
    source_tier: str | None = None
    limitations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('canonical_id', 'name', 'slug', 'source_id', 'source_url'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SnapshotError(f'a model snapshot needs a non-empty {name}')
        parse_timestamp(self.fetched_at)
        if self.freshness not in FRESHNESS_VALUES:
            raise SnapshotError(
                f'unknown freshness {self.freshness!r}; expected one of '
                f'{FRESHNESS_VALUES}')
        if self.modalities is not None:
            if any(not isinstance(item, str) or not item.strip()
                   for item in self.modalities):
                raise SnapshotError('modalities entries must be non-empty strings')
        if self.context_tokens is not None and (
                isinstance(self.context_tokens, bool)
                or not isinstance(self.context_tokens, int)
                or self.context_tokens <= 0):
            raise SnapshotError('context_tokens must be a positive integer or None')
        if self.reasoning_model not in (True, False, None):
            raise SnapshotError('reasoning_model must be True, False or None')
        names = [item.name for item in self.evaluations]
        if len(names) != len(set(names)):
            raise SnapshotError(f'{self.canonical_id}: duplicate evaluation name')

    @property
    def identity_known(self):
        return bool(self.canonical_id)

    @property
    def family_known(self):
        return bool(self.model_family)

    def matches(self, identifier):
        """Exact match on canonical id or slug; no fuzzy name inference."""
        return str(identifier) in (self.canonical_id, self.slug)

    def evaluation(self, name):
        for item in self.evaluations:
            if item.name == name:
                return item
        return None

    def as_dict(self):
        return {
            'canonical_id': self.canonical_id,
            'name': self.name,
            'slug': self.slug,
            'creator': {
                'id': self.creator_id if self.creator_id is not None else UNKNOWN,
                'name': (self.creator_name if self.creator_name is not None
                         else UNKNOWN),
            },
            'model_family': (self.model_family if self.model_family is not None
                             else UNKNOWN),
            'modalities': (list(self.modalities)
                           if self.modalities is not None else UNKNOWN),
            'context_tokens': (self.context_tokens
                               if self.context_tokens is not None else UNKNOWN),
            'reasoning_model': (self.reasoning_model
                                if self.reasoning_model is not None else UNKNOWN),
            'release_date': (self.release_date
                             if self.release_date is not None else UNKNOWN),
            'evaluations': [item.as_dict() for item in self.evaluations],
            'pricing': (self.pricing.as_dict() if self.pricing is not None
                        else UNKNOWN),
            'performance': (self.performance.as_dict()
                            if self.performance is not None else UNKNOWN),
            'source': {
                'source_id': self.source_id,
                'url': self.source_url,
                'tier': (self.source_tier if self.source_tier is not None
                         else UNKNOWN),
                'fetched_at': self.fetched_at,
                'freshness': self.freshness,
                'fetched_at_source': 'fetch',
            },
            'limitations': list(self.limitations),
            'notes': list(self.notes),
        }


@dataclass(frozen=True)
class FetchRecord:
    """The outcome of one fetch attempt (live read or cache fallback)."""

    source_id: str
    source_url: str
    status: str
    fetched_at: str
    live_failure_status: str | None = None
    http_status: int | None = None
    message: str = ''
    tier: str | None = None
    index_version: str | None = None
    used_cache: bool = False
    cache_age_seconds: float | None = None
    max_age_seconds: int | None = None
    requests: int = 0
    rate_limit_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: str | None = None
    retry_after_seconds: int | None = None
    models_returned: int = 0
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('source_id', 'source_url'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SnapshotError(f'a fetch record needs a non-empty {name}')
        if self.status not in FETCH_STATUSES:
            raise SnapshotError(
                f'unknown fetch status {self.status!r}; expected one of '
                f'{FETCH_STATUSES}')
        parse_timestamp(self.fetched_at)
        if self.live_failure_status is not None:
            if self.live_failure_status not in FETCH_STATUSES:
                raise SnapshotError(
                    f'unknown live failure status {self.live_failure_status!r}')
            if self.live_failure_status in FETCH_LIVE_STATUSES:
                raise SnapshotError(
                    'live_failure_status must describe a failed live read')
            if self.status not in (FETCH_CACHED, FETCH_STALE_CACHE):
                raise SnapshotError(
                    'live_failure_status is only meaningful for a cache read')
        if self.used_cache and self.status not in (
                FETCH_CACHED, FETCH_STALE_CACHE):
            raise SnapshotError(
                'used_cache is only valid for CACHED / STALE_CACHE')
        if self.status in (FETCH_CACHED, FETCH_STALE_CACHE) and not self.used_cache:
            raise SnapshotError(
                f'{self.status} must declare used_cache=True')
        value = self.cache_age_seconds
        if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise SnapshotError(
                'cache_age_seconds must be a non-negative number or None')
        for name in ('max_age_seconds', 'requests', 'rate_limit_limit',
                     'rate_limit_remaining', 'retry_after_seconds',
                     'models_returned'):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool)
                                      or not isinstance(value, int)
                                      or value < 0):
                raise SnapshotError(f'{name} must be a non-negative integer')

    @property
    def live(self):
        """Only a successful current read may be called live/latest."""
        return self.status in FETCH_LIVE_STATUSES

    @property
    def usable(self):
        """Fresh cache is usable evidence; an expired cache is not."""
        return self.status in FETCH_USABLE_STATUSES

    @property
    def freshness(self):
        if self.status == FETCH_OK:
            return FRESHNESS_FRESH
        if self.status == FETCH_CACHED:
            return FRESHNESS_FRESH
        if self.status == FETCH_STALE_CACHE:
            return FRESHNESS_STALE
        return FRESHNESS_UNKNOWN

    def as_dict(self):
        return {
            'source_id': self.source_id,
            'source_url': self.source_url,
            'status': self.status,
            'live_failure_status': (self.live_failure_status
                                    if self.live_failure_status is not None
                                    else UNKNOWN),
            'live': self.live,
            'usable': self.usable,
            'freshness': self.freshness,
            'fetched_at': self.fetched_at,
            'http_status': (self.http_status
                            if self.http_status is not None else UNKNOWN),
            'message': self.message,
            'tier': self.tier if self.tier is not None else UNKNOWN,
            'index_version': (self.index_version
                              if self.index_version is not None else UNKNOWN),
            'used_cache': self.used_cache,
            'cache_age_seconds': (self.cache_age_seconds
                                  if self.cache_age_seconds is not None
                                  else UNKNOWN),
            'max_age_seconds': (self.max_age_seconds
                                if self.max_age_seconds is not None
                                else UNKNOWN),
            'requests': self.requests,
            'rate_limit_limit': (self.rate_limit_limit
                                 if self.rate_limit_limit is not None
                                 else UNKNOWN),
            'rate_limit_remaining': (self.rate_limit_remaining
                                     if self.rate_limit_remaining is not None
                                     else UNKNOWN),
            'rate_limit_reset': (self.rate_limit_reset
                                 if self.rate_limit_reset is not None
                                 else UNKNOWN),
            'retry_after_seconds': (self.retry_after_seconds
                                    if self.retry_after_seconds is not None
                                    else UNKNOWN),
            'models_returned': self.models_returned,
            'limitations': list(self.limitations),
        }


@dataclass(frozen=True)
class SnapshotBatch:
    """Every model snapshot from one fetch, plus the fetch outcome."""

    source_id: str
    fetch: FetchRecord
    models: tuple[ModelSnapshot, ...] = ()
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.source_id != self.fetch.source_id:
            raise SnapshotError(
                f'batch source {self.source_id!r} does not match fetch source '
                f'{self.fetch.source_id!r}')
        for model in self.models:
            if model.source_id != self.source_id:
                raise SnapshotError(
                    f'{model.canonical_id}: model source {model.source_id!r} '
                    f'does not match batch source {self.source_id!r}')

    @property
    def usable(self):
        return self.fetch.usable

    @property
    def live(self):
        return self.fetch.live

    def model(self, identifier):
        """Exact lookup by canonical id or slug; ``None`` when not present."""
        for snapshot in self.models:
            if snapshot.matches(identifier):
                return snapshot
        return None

    def as_dict(self):
        return {
            'source_id': self.source_id,
            'fetch': self.fetch.as_dict(),
            'models': [model.as_dict() for model in self.models],
            'warnings': list(self.warnings),
            'notes': list(self.notes),
        }


@dataclass(frozen=True)
class CacheEntry:
    """One stored batch and the time it was stored (UTC)."""

    key: str
    stored_at: str
    batch: SnapshotBatch

    def __post_init__(self):
        if not isinstance(self.key, str) or not self.key.strip():
            raise SnapshotError('a cache entry needs a key')
        parse_timestamp(self.stored_at)
        if self.batch.fetch.status != FETCH_OK:
            raise SnapshotError(
                'only a successful fetch (OK) may be cached; refusing to cache '
                f'{self.batch.fetch.status}')


@dataclass(frozen=True)
class CacheHit:
    """A cache entry plus its age at read time."""

    entry: CacheEntry
    age_seconds: float
    fresh: bool

    def as_dict(self):
        return {'key': self.entry.key, 'stored_at': self.entry.stored_at,
                'age_seconds': self.age_seconds, 'fresh': self.fresh}


class SnapshotCache:
    """In-memory cache with an explicit freshness window.

    There is no filesystem default: a caller decides whether a cache exists at
    all. That keeps the base CLI offline and makes tests deterministic. The
    cache only accepts a successful live fetch, so a schema-changed or limited
    response cannot overwrite a good snapshot.
    """

    def __init__(self, *, max_age_seconds=DEFAULT_MAX_AGE_SECONDS):
        if isinstance(max_age_seconds, bool) or not isinstance(
                max_age_seconds, int) or max_age_seconds <= 0:
            raise SnapshotError('max_age_seconds must be a positive integer')
        self.max_age_seconds = max_age_seconds
        self._entries = {}

    def store(self, key, batch, *, now=None):
        if not isinstance(batch, SnapshotBatch):
            raise SnapshotError('only a SnapshotBatch can be cached')
        if batch.fetch.status != FETCH_OK:
            raise SnapshotError(
                f'refusing to cache a {batch.fetch.status} batch')
        entry = CacheEntry(key=str(key), stored_at=utc_timestamp(now),
                           batch=batch)
        self._entries[entry.key] = entry
        return entry

    def load(self, key, *, now=None):
        entry = self._entries.get(str(key))
        if entry is None:
            return None
        age = age_seconds(entry.stored_at, now)
        if age is None:
            return CacheHit(entry=entry, age_seconds=0.0, fresh=False)
        return CacheHit(entry=entry, age_seconds=age,
                        fresh=age <= self.max_age_seconds)

    def clear(self):
        self._entries.clear()

    def __len__(self):
        return len(self._entries)


def stale_batch(batch, *, status, message, http_status=None, now=None,
                cache_age_seconds=None, max_age_seconds=None,
                requests=0, retry_after_seconds=None,
                live_failure_status=None):
    """Re-label a cached batch as CACHED / STALE_CACHE at read time.

    The models keep their original ``fetched_at`` (the data time) but their
    freshness becomes ``STALE`` for an expired cache. Nothing is rewritten to
    look newer than it is.
    """
    if status not in (FETCH_CACHED, FETCH_STALE_CACHE):
        raise SnapshotError('stale_batch only labels cache reads')
    freshness = (FRESHNESS_FRESH if status == FETCH_CACHED
                 else FRESHNESS_STALE)
    models = tuple(replace(model, freshness=freshness)
                   for model in batch.models)
    fetch = FetchRecord(
        source_id=batch.source_id,
        source_url=batch.fetch.source_url,
        status=status,
        fetched_at=utc_timestamp(now),
        live_failure_status=live_failure_status,
        http_status=http_status,
        message=message,
        tier=batch.fetch.tier,
        index_version=batch.fetch.index_version,
        used_cache=True,
        cache_age_seconds=(round(cache_age_seconds, 3)
                           if cache_age_seconds is not None else None),
        max_age_seconds=max_age_seconds,
        requests=requests,
        rate_limit_limit=batch.fetch.rate_limit_limit,
        rate_limit_remaining=batch.fetch.rate_limit_remaining,
        rate_limit_reset=batch.fetch.rate_limit_reset,
        retry_after_seconds=retry_after_seconds,
        models_returned=len(models),
        limitations=batch.fetch.limitations + (
            'served from cache; this is not a live / latest reading'
            if status == FETCH_CACHED else
            'cache is older than the freshness window and is STALE; it is not '
            'usable as current evidence',),
    )
    return SnapshotBatch(source_id=batch.source_id, fetch=fetch, models=models,
                         warnings=batch.warnings, notes=batch.notes)
