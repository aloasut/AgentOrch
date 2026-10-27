#!/usr/bin/env python3
"""Artificial Analysis Data API adapter (#122, S3).

Official contract (verified 2026-10-27):

* <https://artificialanalysis.ai/data-api>
* <https://artificialanalysis.ai/data-api/docs>
* <https://artificialanalysis.ai/data-api/docs/reference> (the page behind
  ``https://artificialanalysis.ai/api-reference/`` links to a legacy free-API
  description; this adapter uses the current ``/api/v2`` reference)

Facts this module relies on, all re-checked before implementation:

* base URL ``https://artificialanalysis.ai/api/v2``;
* authentication is a key in the ``x-api-key`` header (no OAuth / signing);
* the language list is ``GET /api/v2/language/models/free`` on every tier and
  ``GET /api/v2/language/models`` on Pro / Commercial;
* responses carry ``tier``, ``intelligence_index_version``, ``pagination`` and
  ``data``; dates are ISO 8601 and ``null`` means "not measured", never zero;
* Free omits Pro fields such as modalities, context window, per-benchmark
  scores and percentiles — an omitted field is a subscription-shape limit, not
  evidence that the model lacks the capability;
* quotas are 100 / 500 / custom requests per fixed 24-hour window for Free /
  Pro / Commercial; ``X-RateLimit-*`` describe the window and a ``429`` adds
  ``Retry-After``;
* ``401`` is a bad/missing key, ``403`` means the tier does not cover the
  endpoint, ``429`` is the daily limit, ``500`` is a server error.

The adapter is intentionally narrow: no scraping, no third-party client, no
bundled model names, ranks or prices. A key is read from a protected
environment variable at request time and is never stored on the object, put in
``repr``, written to a record or embedded in an error message.

Standard library only. Tests inject a fake transport and never touch the
network; the default transport uses :mod:`urllib`.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from .snapshot import (
    FETCH_AUTH_FAILED,
    FETCH_CACHED,
    FETCH_HTTP_ERROR,
    FETCH_NETWORK_ERROR,
    FETCH_NO_CREDENTIAL,
    FETCH_OK,
    FETCH_RATE_LIMITED,
    FETCH_SCHEMA_CHANGED,
    FETCH_SERVER_ERROR,
    FETCH_STALE_CACHE,
    FETCH_TIER_RESTRICTED,
    FETCH_TIMEOUT,
    FETCH_UNPARSEABLE,
    FRESHNESS_FRESH,
    UNKNOWN,
    FetchRecord,
    ModelEvaluation,
    ModelPerformance,
    ModelPricing,
    ModelSnapshot,
    SnapshotBatch,
    SnapshotCache,
    SnapshotError,
    stale_batch,
    utc_timestamp,
)

__all__ = [
    'SOURCE_ID',
    'SOURCE_LABEL',
    'BASE_URL',
    'FREE_MODELS_PATH',
    'PRO_MODELS_PATH',
    'DEFAULT_ENDPOINT',
    'DEFAULT_API_KEY_ENV',
    'DEFAULT_TIMEOUT_SECONDS',
    'DEFAULT_MAX_PAGES',
    'OFFICIAL_HOSTS',
    'TransportError',
    'TransportTimeout',
    'HttpRequest',
    'HttpResponse',
    'UrllibTransport',
    'ArtificialAnalysisSource',
]

SOURCE_ID = 'artificial-analysis'
SOURCE_LABEL = 'Artificial Analysis Data API'
BASE_URL = 'https://artificialanalysis.ai/api/v2'
FREE_MODELS_PATH = '/language/models/free'
PRO_MODELS_PATH = '/language/models'
DEFAULT_ENDPOINT = BASE_URL + FREE_MODELS_PATH
DEFAULT_API_KEY_ENV = 'ARTIFICIAL_ANALYSIS_API_KEY'
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_PAGES = 3
OFFICIAL_HOSTS = ('artificialanalysis.ai', 'www.artificialanalysis.ai')

_REQUIRED_MODEL_KEYS = ('id', 'name', 'slug', 'model_creator', 'evaluations',
                        'pricing', 'performance')

# Evaluation keys whose value is a 0..1 proportion rather than a 0..100 index.
_PROPORTION_KEYS = {
    'mmlu_pro', 'gpqa', 'gpqa_diamond', 'hle', 'livecodebench', 'scicode',
    'math_500', 'aime', 'ifbench', 'tau2_telecom', 'tau_banking',
    'terminalbench_hard', 'terminalbench_v2_1', 'terminalbench_v4_0',
    'automationbench_aa', 'gdp_pdf', 'aa_lcr', 'aa_omniscience_accuracy',
    'aa_omniscience_non_hallucination_rate', 'gdpval_aa_normalized',
    'artificial_analysis_multilingual_index', 'critpt',
}

_LIMITATIONS = (
    'model family is not published by this source; family stays UNKNOWN',
    'benchmark sample counts and coverage are not published by this source',
    'provider-published scores were not verified by a local model run',
    'null means not measured or not applicable and is never read as zero',
)

_FREE_SHAPE_NOTE = (
    'the Free-shape response omits Pro-only fields (modalities, context window, '
    'per-benchmark scores, percentiles); an omitted field is a subscription '
    'limit, not evidence that the model lacks the capability')


class TransportError(OSError):
    """The injected transport could not complete the request."""


class TransportTimeout(TransportError):
    """The injected transport exceeded its timeout."""


@dataclass(frozen=True)
class HttpRequest:
    """One GET request; headers are pairs so the object stays hashable."""

    method: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def header(self, name):
        folded = str(name).casefold()
        for key, value in self.headers:
            if key.casefold() == folded:
                return value
        return None

    def as_dict(self):
        # Headers are deliberately omitted: one of them is the API key.
        return {'method': self.method, 'url': self.url,
                'timeout_seconds': self.timeout_seconds}


@dataclass(frozen=True)
class HttpResponse:
    """A transport response; ``body`` is text and may be empty."""

    status: int
    headers: tuple[tuple[str, str], ...] = ()
    body: str = ''

    def header(self, name):
        folded = str(name).casefold()
        for key, value in self.headers:
            if key.casefold() == folded:
                return value
        return None

    def as_dict(self):
        return {'status': self.status, 'headers': dict(self.headers),
                'body_length': len(self.body)}


class UrllibTransport:
    """Default transport using the standard library.

    It is only constructed by :class:`ArtificialAnalysisSource`; importing the
    module performs no I/O. Tests replace it with a callable fixture.
    """

    def __call__(self, request):
        if not isinstance(request, HttpRequest):
            raise TransportError('transport expects an HttpRequest')
        url_request = urllib.request.Request(
            request.url, headers=dict(request.headers), method=request.method)
        try:
            with urllib.request.urlopen(
                    url_request, timeout=request.timeout_seconds) as response:
                return HttpResponse(
                    status=int(getattr(response, 'status', 0) or 0),
                    headers=tuple(response.headers.items()),
                    body=response.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8', 'replace')
            except Exception:  # pragma: no cover - defensive only
                body = ''
            return HttpResponse(
                status=int(exc.code), headers=tuple(exc.headers.items())
                if exc.headers is not None else (), body=body)
        except (socket.timeout, TimeoutError) as exc:
            raise TransportTimeout('request timed out') from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise TransportTimeout('request timed out') from exc
            raise TransportError(f'network error: {exc.reason}') from exc
        except OSError as exc:
            raise TransportError(f'network error: {exc}') from exc


class _FetchFailure(Exception):
    """Internal carrier for one failed fetch outcome."""

    def __init__(self, status, message, *, http_status=None,
                 retry_after_seconds=None, requests=0):
        super().__init__(message)
        self.status = status
        self.message = message
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.requests = requests


def _official_endpoint(endpoint):
    parsed = urlparse(str(endpoint))
    if (parsed.scheme != 'https' or parsed.hostname not in OFFICIAL_HOSTS
            or not parsed.path.startswith('/api/v2/')):
        raise SnapshotError(
            'the Artificial Analysis adapter only accepts the official HTTPS '
            f'Data API under {BASE_URL} (got {endpoint!r}); scraping another '
            'host or page is outside this contract')
    return str(endpoint)


def _redact(text, secret):
    if secret and text:
        return str(text).replace(secret, '[REDACTED]')
    return str(text or '')


def _header_int(headers, name):
    value = headers.header(name)
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _unit_and_scope(name):
    if name in _PROPORTION_KEYS:
        return 'proportion', 'benchmark'
    if name.endswith('_index') and name != 'artificial_analysis_multilingual_index':
        return 'index', 'composite'
    if name.endswith('_elo'):
        return 'elo', 'arena'
    return UNKNOWN, ''


def _index_version_applies(name):
    return (name.startswith('artificial_analysis_') and name.endswith('_index')
            and name != 'artificial_analysis_multilingual_index')


class ArtificialAnalysisSource:
    """Fetch language-model snapshots from the official Data API.

    Parameters
    ----------
    endpoint:
        Official ``/api/v2`` URL. Defaults to the Free-shape language list,
        which accepts every valid key. Passing the Pro list is allowed; a tier
        that does not cover it yields ``TIER_RESTRICTED``.
    api_key_env:
        Name of the protected environment variable holding the key. The key
        itself is read per request and never kept.
    transport:
        Callable ``HttpRequest -> HttpResponse``. Tests inject a fixture.
    cache:
        Optional :class:`SnapshotCache`. It is only consulted after a live
        fetch fails; a successful fetch replaces it.
    """

    def __init__(self, *, endpoint=DEFAULT_ENDPOINT,
                 api_key_env=DEFAULT_API_KEY_ENV, transport=None,
                 timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                 max_pages=DEFAULT_MAX_PAGES, cache=None):
        self.endpoint = _official_endpoint(endpoint)
        if not isinstance(api_key_env, str) or not api_key_env.strip():
            raise SnapshotError('api_key_env must name a protected environment variable')
        self.api_key_env = api_key_env
        if isinstance(timeout_seconds, bool) or not isinstance(
                timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise SnapshotError('timeout_seconds must be positive')
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) \
                or max_pages <= 0:
            raise SnapshotError('max_pages must be a positive integer')
        if cache is not None and not isinstance(cache, SnapshotCache):
            raise SnapshotError('cache must be a SnapshotCache instance')
        self.timeout_seconds = float(timeout_seconds)
        self.max_pages = max_pages
        self.cache = cache
        self._transport = transport if transport is not None else UrllibTransport()

    def __repr__(self):
        # Keep this string free of the key: only its presence is reported.
        return (f'<ArtificialAnalysisSource endpoint={self.endpoint!r} '
                f'api_key_env={self.api_key_env!r} '
                f'key_present={bool(os.environ.get(self.api_key_env))}>')

    @property
    def cache_key(self):
        return f'{SOURCE_ID}:{self.endpoint}'

    def fetch(self, *, now=None):
        """Return one :class:`SnapshotBatch`; never raise for a fetch outcome."""
        fetched_at = utc_timestamp(now)
        api_key = os.environ.get(self.api_key_env, '')
        if not isinstance(api_key, str) or not api_key.strip():
            return self._degrade(
                FETCH_NO_CREDENTIAL,
                f'{self.api_key_env} is not set; no request was made',
                now=fetched_at, requests=0)
        try:
            return self._fetch_live(api_key.strip(), fetched_at)
        except _FetchFailure as failure:
            return self._degrade(
                failure.status, failure.message, now=fetched_at,
                http_status=failure.http_status,
                retry_after_seconds=failure.retry_after_seconds,
                requests=failure.requests)

    # -- live fetch --------------------------------------------------------
    def _fetch_live(self, api_key, fetched_at):
        page = 1
        models = []
        seen = set()
        issues = []
        warnings = []
        tier = None
        index_version = None
        requests_made = 0
        rate_limit = {}
        while page <= self.max_pages:
            response = self._request_page(api_key, page)
            requests_made += 1
            rate_limit = {
                'limit': _header_int(response, 'X-RateLimit-Limit'),
                'remaining': _header_int(response, 'X-RateLimit-Remaining'),
                'reset': response.header('X-RateLimit-Reset'),
            }
            payload = self._decode(response)
            page_models, page_issues, page_tier, page_version, has_more, \
                total_pages = self._parse_page(payload, fetched_at)
            issues.extend(page_issues)
            if tier is None:
                tier = page_tier
            elif page_tier != tier:
                warnings.append(
                    f'response tier changed between pages ({tier!r} -> '
                    f'{page_tier!r}); the first tier is reported')
            if index_version is None:
                index_version = page_version
            elif page_version != index_version:
                raise _FetchFailure(
                    FETCH_SCHEMA_CHANGED,
                    'intelligence_index_version changed between pages '
                    f'({index_version!r} -> {page_version!r}); scores from '
                    'different index versions are not mixed')
            for snapshot in page_models:
                if snapshot.canonical_id in seen:
                    warnings.append(
                        f'{snapshot.canonical_id}: duplicate row across pages; '
                        'the first occurrence is kept')
                    continue
                seen.add(snapshot.canonical_id)
                models.append(snapshot)
            if not has_more:
                break
            if page >= self.max_pages:
                warnings.append(
                    f'partial snapshot: stopped after {self.max_pages} page(s) '
                    f'of {total_pages if total_pages is not None else UNKNOWN}; '
                    'later models are not part of this batch')
                break
            page += 1

        if not models and issues:
            raise _FetchFailure(
                FETCH_SCHEMA_CHANGED,
                'no model row could be parsed; first issue: ' + issues[0],
                requests=requests_made)

        limitations = list(_LIMITATIONS)
        if self.endpoint.endswith('/free') or tier == 'free':
            limitations.append(_FREE_SHAPE_NOTE)
        if not models:
            warnings.append('the source returned no model rows')

        fetch = FetchRecord(
            source_id=SOURCE_ID,
            source_url=self.endpoint,
            status=FETCH_OK,
            fetched_at=fetched_at,
            http_status=200,
            message='live read from the official Data API',
            tier=tier,
            index_version=index_version,
            requests=requests_made,
            rate_limit_limit=rate_limit.get('limit'),
            rate_limit_remaining=rate_limit.get('remaining'),
            rate_limit_reset=rate_limit.get('reset'),
            models_returned=len(models),
        )
        batch = SnapshotBatch(
            source_id=SOURCE_ID, fetch=fetch, models=tuple(models),
            warnings=tuple(dict.fromkeys(warnings + issues)),
            notes=(
                'Artificial Analysis is the first external reference, not a '
                'sole source of truth; a score never grants a capability',
                'this batch is a live read at the recorded fetched_at time',
            ))
        if self.cache is not None:
            self.cache.store(self.cache_key, batch, now=fetched_at)
        return batch

    def _request_page(self, api_key, page):
        url = self.endpoint
        if page > 1:
            url = (url + ('&' if '?' in url else '?') + f'page={page}')
        request = HttpRequest(
            method='GET',
            url=url,
            headers=(
                ('x-api-key', api_key),
                ('accept', 'application/json'),
                ('user-agent', 'AgentOrch-model-sources/1'),
            ),
            timeout_seconds=self.timeout_seconds,
        )
        try:
            response = self._transport(request)
        except TransportTimeout as exc:
            raise _FetchFailure(FETCH_TIMEOUT, _redact(exc, api_key),
                                requests=page) from exc
        except TransportError as exc:
            raise _FetchFailure(FETCH_NETWORK_ERROR, _redact(exc, api_key),
                                requests=page) from exc
        except Exception as exc:  # an injected transport must not crash us
            raise _FetchFailure(
                FETCH_NETWORK_ERROR,
                f'{type(exc).__name__}: {_redact(exc, api_key)}',
                requests=page) from exc
        if not isinstance(response, HttpResponse):
            raise _FetchFailure(
                FETCH_NETWORK_ERROR,
                'the transport returned an unsupported response object',
                requests=page)
        if response.status != 200:
            raise self._http_failure(response, api_key, requests=page)
        return response

    def _http_failure(self, response, api_key, *, requests=0):
        status = int(response.status)
        detail = ''
        try:
            payload = json.loads(response.body) if response.body else None
            if isinstance(payload, dict) and isinstance(payload.get('error'), str):
                detail = ': ' + _redact(payload['error'], api_key)[:200]
        except (TypeError, ValueError):
            detail = ''
        retry_after = _header_int(response, 'Retry-After')
        if status == 401:
            return _FetchFailure(
                FETCH_AUTH_FAILED,
                'authentication failed (HTTP 401): missing, invalid or revoked '
                'API key' + detail,
                http_status=status, retry_after_seconds=retry_after,
                requests=requests)
        if status == 403:
            return _FetchFailure(
                FETCH_TIER_RESTRICTED,
                'the current subscription does not cover this endpoint '
                '(HTTP 403); this is a tier limit, not evidence that a model '
                'lacks a capability' + detail,
                http_status=status, retry_after_seconds=retry_after,
                requests=requests)
        if status == 429:
            suffix = (f'; retry after {retry_after}s' if retry_after is not None
                      else '')
            return _FetchFailure(
                FETCH_RATE_LIMITED,
                f'daily rate limit exhausted (HTTP 429){suffix}' + detail,
                http_status=status, retry_after_seconds=retry_after,
                requests=requests)
        if status >= 500:
            return _FetchFailure(
                FETCH_SERVER_ERROR,
                f'the provider returned HTTP {status}' + detail,
                http_status=status, retry_after_seconds=retry_after,
                requests=requests)
        return _FetchFailure(
            FETCH_HTTP_ERROR, f'the provider returned HTTP {status}' + detail,
            http_status=status, retry_after_seconds=retry_after)

    def _decode(self, response):
        try:
            payload = json.loads(response.body)
        except (TypeError, ValueError) as exc:
            raise _FetchFailure(
                FETCH_UNPARSEABLE,
                f'the response body is not valid JSON: {type(exc).__name__}',
                http_status=response.status) from exc
        if not isinstance(payload, dict):
            raise _FetchFailure(
                FETCH_SCHEMA_CHANGED,
                'the response envelope is not a JSON object',
                http_status=response.status)
        return payload

    def _parse_page(self, payload, fetched_at):
        for key in ('tier', 'intelligence_index_version', 'pagination', 'data'):
            if key not in payload:
                raise _FetchFailure(
                    FETCH_SCHEMA_CHANGED,
                    f'the response envelope lost the required {key!r} field',
                    http_status=200)
        tier = payload['tier']
        if not isinstance(tier, str) or not tier.strip():
            raise _FetchFailure(
                FETCH_SCHEMA_CHANGED,
                'the response envelope tier is not a non-empty string',
                http_status=200)
        version = payload['intelligence_index_version']
        if isinstance(version, bool) or not isinstance(version, (int, float)):
            raise _FetchFailure(
                FETCH_SCHEMA_CHANGED,
                'intelligence_index_version is not numeric; scores cannot be '
                'attributed to an index version',
                http_status=200)
        pagination = payload['pagination']
        if not isinstance(pagination, dict):
            raise _FetchFailure(
                FETCH_SCHEMA_CHANGED,
                'the pagination field is not an object',
                http_status=200)
        data = payload['data']
        if not isinstance(data, list):
            raise _FetchFailure(
                FETCH_SCHEMA_CHANGED,
                'the data field is not a list of model rows',
                http_status=200)

        models = []
        issues = []
        for index, item in enumerate(data):
            try:
                models.append(self._parse_model(item, fetched_at, tier,
                                                version))
            except SnapshotError as exc:
                issues.append(f'row {index}: {exc}; skipped')
        return (models, issues, tier, str(version),
                bool(pagination.get('has_more')),
                pagination.get('total_pages'))

    def _parse_model(self, item, fetched_at, tier, version):
        if not isinstance(item, dict):
            raise SnapshotError('the model row is not an object')
        missing = [key for key in _REQUIRED_MODEL_KEYS if key not in item]
        if missing:
            raise SnapshotError(
                f'the model row is missing {", ".join(missing)}')
        for key in ('id', 'name', 'slug'):
            if not isinstance(item[key], str) or not item[key].strip():
                raise SnapshotError(f'{key} is not a non-empty string')
        creator = item['model_creator']
        if not isinstance(creator, dict) or not isinstance(
                creator.get('name'), str) or not creator['name'].strip():
            raise SnapshotError('model_creator.name is not a non-empty string')

        issues = []
        evaluations = tuple(self._parse_evaluations(
            item['evaluations'], version, issues))
        pricing = self._parse_pricing(item['pricing'], issues)
        performance = self._parse_performance(item['performance'], issues)
        modalities = self._parse_modalities(item.get('modalities'), issues)
        context_tokens = self._parse_positive_int(
            item.get('context_window_tokens'), 'context_window_tokens', issues)
        reasoning = item.get('reasoning_model')
        if reasoning is not None and not isinstance(reasoning, bool):
            issues.append('reasoning_model is not a boolean; left UNKNOWN')
            reasoning = None
        release_date = item.get('release_date')
        if release_date is not None and not isinstance(release_date, str):
            issues.append('release_date is not a string; left UNKNOWN')
            release_date = None
        if isinstance(release_date, str) and not release_date.strip():
            release_date = None

        limitations = list(_LIMITATIONS)
        if self.endpoint.endswith('/free') or tier == 'free':
            limitations.append(_FREE_SHAPE_NOTE)
        if modalities is None:
            limitations.append(
                'input modalities were not present in this response; they '
                'stay UNKNOWN rather than being inferred from the model name')
        if context_tokens is None:
            limitations.append(
                'context window was not present in this response; it stays '
                'UNKNOWN')
        if not pricing.known:
            limitations.append(
                'no price was published for this row; cost stays UNKNOWN')
        if not performance.known:
            limitations.append(
                'no latency / throughput was published for this row; it stays '
                'UNKNOWN')
        if not any(evaluation.known for evaluation in evaluations):
            limitations.append(
                'no numeric evaluation was published for this row; every score '
                'stays UNKNOWN')

        return ModelSnapshot(
            canonical_id=item['id'].strip(),
            name=item['name'].strip(),
            slug=item['slug'].strip(),
            source_id=SOURCE_ID,
            source_url=self.endpoint,
            fetched_at=fetched_at,
            creator_id=(str(creator['id']).strip()
                        if isinstance(creator.get('id'), str)
                        and creator['id'].strip() else None),
            creator_name=creator['name'].strip(),
            # The provider does not publish a canonical family; do not infer
            # one from a display name or a slug.
            model_family=None,
            modalities=modalities,
            context_tokens=context_tokens,
            reasoning_model=reasoning,
            release_date=release_date,
            evaluations=evaluations,
            pricing=pricing,
            performance=performance,
            freshness=FRESHNESS_FRESH,
            source_tier=tier,
            limitations=tuple(dict.fromkeys(limitations)),
            notes=tuple(issues),
        )

    def _parse_evaluations(self, value, version, issues):
        if not isinstance(value, dict):
            raise SnapshotError('evaluations is not an object')
        evaluations = []
        for name, raw in value.items():
            if not isinstance(name, str) or not name.strip():
                issues.append('an evaluation key is not a name; skipped')
                continue
            if raw is None:
                unit, scope = _unit_and_scope(name)
                evaluations.append(ModelEvaluation(
                    name=name, value=None, unit=unit, scope=scope,
                    note='the provider published null (not measured)'))
                continue
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                issues.append(
                    f'evaluation {name!r} is not numeric; skipped instead of '
                    'coerced')
                continue
            unit, scope = _unit_and_scope(name)
            index_version = str(version) if _index_version_applies(name) else None
            evaluations.append(ModelEvaluation(
                name=name, value=float(raw), unit=unit,
                index_version=index_version, scope=scope))
        return evaluations

    def _parse_pricing(self, value, issues):
        if not isinstance(value, dict):
            raise SnapshotError('pricing is not an object')
        fields = {
            'input_per_mtok': 'price_1m_input_tokens',
            'output_per_mtok': 'price_1m_output_tokens',
            'cache_read_per_mtok': 'price_1m_cache_hit_tokens',
            'cache_write_per_mtok': 'price_1m_cache_write_tokens',
            'blended_3_to_1_per_mtok': 'price_1m_blended_3_to_1',
        }
        parsed = {}
        for name, key in fields.items():
            raw = value.get(key)
            if raw is None:
                parsed[name] = None
                continue
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                issues.append(f'{key} is not numeric; left UNKNOWN')
                parsed[name] = None
                continue
            parsed[name] = float(raw)
        return ModelPricing(**parsed)

    def _parse_performance(self, value, issues):
        if not isinstance(value, dict):
            raise SnapshotError('performance is not an object')
        fields = {
            'output_tokens_per_second': 'median_output_tokens_per_second',
            'time_to_first_token_seconds': 'median_time_to_first_token_seconds',
            'time_to_first_answer_token_seconds':
                'median_time_to_first_answer_token_seconds',
            'end_to_end_response_time_seconds':
                'median_end_to_end_response_time_seconds',
        }
        parsed = {}
        for name, key in fields.items():
            raw = value.get(key)
            if raw is None:
                parsed[name] = None
                continue
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                issues.append(f'{key} is not numeric; left UNKNOWN')
                parsed[name] = None
                continue
            parsed[name] = float(raw)
        return ModelPerformance(**parsed)

    def _parse_modalities(self, value, issues):
        if value is None:
            return None
        if not isinstance(value, dict):
            issues.append('modalities is not an object; left UNKNOWN')
            return None
        inputs = value.get('input')
        if not isinstance(inputs, dict):
            issues.append('modalities.input is not an object; left UNKNOWN')
            return None
        observed = []
        for name, enabled in inputs.items():
            if not isinstance(name, str) or not isinstance(enabled, bool):
                issues.append(
                    'modalities.input contains a non-boolean entry; the whole '
                    'modality set is left UNKNOWN')
                return None
            if enabled:
                observed.append(name)
        return tuple(observed)

    def _parse_positive_int(self, value, name, issues):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            issues.append(f'{name} is not a positive integer; left UNKNOWN')
            return None
        return value

    # -- degradation -------------------------------------------------------
    def _degrade(self, status, message, *, now, http_status=None,
                 retry_after_seconds=None, requests=0):
        hit = self._cache_hit(now)
        if hit is None:
            return self._empty(status, message, now=now,
                               http_status=http_status,
                               retry_after_seconds=retry_after_seconds,
                               requests=requests)
        cache_status = FETCH_CACHED if hit.fresh else FETCH_STALE_CACHE
        cache_message = (
            f'live fetch failed: {status}: {message}; serving '
            f'{"a fresh" if hit.fresh else "an expired"} cache entry '
            f'({hit.age_seconds:.0f}s old)')
        batch = stale_batch(
            hit.entry.batch, status=cache_status, message=cache_message,
            http_status=http_status, now=now,
            cache_age_seconds=hit.age_seconds,
            max_age_seconds=self.cache.max_age_seconds,
            requests=requests, retry_after_seconds=retry_after_seconds,
            live_failure_status=status)
        return batch

    def _cache_hit(self, now=None):
        if self.cache is None:
            return None
        return self.cache.load(self.cache_key, now=now)

    def _empty(self, status, message, *, now, http_status=None,
               retry_after_seconds=None, requests=0):
        fetch = FetchRecord(
            source_id=SOURCE_ID,
            source_url=self.endpoint,
            status=status,
            fetched_at=now,
            http_status=http_status,
            message=message,
            requests=requests,
            retry_after_seconds=retry_after_seconds,
            models_returned=0,
            limitations=('no external evidence was used for this selection',
                         ) if status != FETCH_NO_CREDENTIAL else (
                'no API key was available and no cache existed; UNKNOWN, not '
                'a missing model capability',),
        )
        return SnapshotBatch(
            source_id=SOURCE_ID, fetch=fetch, models=(),
            warnings=(message,),
            notes=('the role selector can still run on S2 evidence; external '
                   'scores are optional',))
