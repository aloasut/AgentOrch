"""Synthetic Artificial Analysis responses for the S3 tests (#122).

Every payload is fixed and local. No test reads the network, a real API key or
a real ``.local`` directory. The field shapes follow the official
``/api/v2/language/models`` reference checked on 2026-10-27, but the values are
invented on purpose so a passing test can never be mistaken for a real model
evaluation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection.model_sources import artificial_analysis  # noqa: E402
from scripts.agent_selection.model_sources.artificial_analysis import (  # noqa: E402
    HttpResponse,
)
from scripts.agent_selection.model_sources.snapshot import (  # noqa: E402
    SnapshotCache,
)

NOW = '2026-10-27T12:00:00Z'
EARLIER = '2026-10-26T12:00:00Z'
LATER = '2026-10-27T13:00:00Z'
EXPIRED = '2026-10-29T12:00:00Z'
API_KEY = 'test-key-not-a-real-credential'

SOURCE_ENDPOINT = artificial_analysis.DEFAULT_ENDPOINT


def json_response(payload, *, status=200, headers=()):
    return HttpResponse(status=status, headers=tuple(headers),
                        body=json.dumps(payload))


def raw_response(body, *, status=200, headers=()):
    return HttpResponse(status=status, headers=tuple(headers), body=body)


def model_row(index=0, *, slug=None, name=None, canonical_id=None,
              evaluations=None, pricing=None, performance=None,
              release_date='2026-01-01', context_window_tokens=200000,
              modalities=None):
    slug = slug or f'model-{index:02d}'
    name = name or f'Fixture Model {index:02d}'
    canonical_id = canonical_id or f'00000000-0000-4000-8000-{index:012d}'
    if evaluations is None:
        evaluations = {
            'artificial_analysis_intelligence_index': 20.0 + index * 5,
            'artificial_analysis_coding_index': 10.0 + index * 8,
            'artificial_analysis_agentic_index': 15.0 + index * 7,
            'artificial_analysis_math_index': 25.0 + index * 6,
            'ifbench': 0.30 + index * 0.05,
            'gpqa_diamond': 0.20 + index * 0.04,
            'livecodebench': 0.10 + index * 0.05,
            'terminalbench_v2_1': 0.05 + index * 0.04,
        }
    if pricing is None:
        pricing = {
            'price_1m_input_tokens': 1.0 + index * 0.1,
            'price_1m_output_tokens': 2.0 + index * 0.2,
        }
    if performance is None:
        performance = {
            'median_output_tokens_per_second': 100.0 + index,
            'median_time_to_first_token_seconds': 1.0 + index * 0.1,
            'median_time_to_first_answer_token_seconds': 1.5 + index * 0.1,
            'median_end_to_end_response_time_seconds': 8.0 + index * 0.5,
        }
    if modalities is None:
        modalities = {
            'input': {'text': True, 'image': index % 2 == 0,
                      'video': False, 'speech': False},
            'output': {'text': True, 'image': False, 'video': False,
                       'speech': False},
        }
    row = {
        'id': canonical_id,
        'name': name,
        'slug': slug,
        'release_date': release_date,
        'model_creator': {
            'id': f'creator-{index:02d}',
            'name': f'Fixture Creator {index:02d}',
        },
        'evaluations': dict(evaluations),
        'pricing': dict(pricing),
        'performance': dict(performance),
    }
    if context_window_tokens is not None:
        row['context_window_tokens'] = context_window_tokens
    if modalities is not None:
        row['modalities'] = modalities
    return row


def payload(rows=None, *, tier='pro', version=4.3, has_more=False,
            page=1, total_pages=1, include_pagination=True,
            include_version=True, include_tier=True):
    rows = [model_row(index) for index in range(10)] if rows is None else rows
    rows = [dict(row) for row in rows]
    if tier == 'free':
        # The real Free shape omits the Pro-only fields.
        for row in rows:
            row.pop('context_window_tokens', None)
            row.pop('modalities', None)
    body = {'data': list(rows)}
    if include_tier:
        body['tier'] = tier
    if include_version:
        body['intelligence_index_version'] = version
    if include_pagination:
        body['pagination'] = {
            'page': page,
            'page_size': 200,
            'total_pages': total_pages,
            'has_more': has_more,
        }
    return body


class FakeTransport:
    """A transport whose responses are supplied by the test."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError('FakeTransport ran out of responses')
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request)
        return item


def source(*, responses=None, transport=None, cache=None, endpoint=None,
           max_pages=None):
    return artificial_analysis.ArtificialAnalysisSource(
        endpoint=endpoint or SOURCE_ENDPOINT,
        transport=transport or FakeTransport(responses or []),
        cache=cache,
        max_pages=max_pages or artificial_analysis.DEFAULT_MAX_PAGES,
        timeout_seconds=5)


def cache(max_age_seconds=24 * 60 * 60):
    return SnapshotCache(max_age_seconds=max_age_seconds)
