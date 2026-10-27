"""Artificial Analysis adapter tests against fixed HTTP fixtures (#122, S3).

No test performs network I/O. A fake transport supplies every response; the
API key is a clearly fake string. The negative matrix covers the required
failure statuses: no key, 401, 403, 429, timeout, network failure, schema
change, unparseable body, fresh cache and expired cache.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection.model_sources import artificial_analysis, snapshot  # noqa: E402
from tests.agent_selection.model_sources import fixtures  # noqa: E402

KEY_ENV = artificial_analysis.DEFAULT_API_KEY_ENV


@contextmanager
def key(value=fixtures.API_KEY):
    with mock.patch.dict(os.environ, {}, clear=False):
        if value is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = value
        yield


def fetch_one(*, payload=None, response=None, cache=None, now=fixtures.NOW,
              max_pages=None, endpoint=None, transport=None):
    if transport is None:
        transport = fixtures.FakeTransport(
            [response if response is not None
             else fixtures.json_response(payload or fixtures.payload())])
    source = fixtures.source(transport=transport, cache=cache,
                             endpoint=endpoint, max_pages=max_pages)
    return source.fetch(now=now)


class SuccessTests(unittest.TestCase):
    def test_free_shape_is_mapped_with_unknown_pro_fields(self):
        with key():
            batch = fetch_one(payload=fixtures.payload(tier='free'))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_OK)
        self.assertTrue(batch.fetch.live)
        self.assertEqual(batch.fetch.tier, 'free')
        self.assertEqual(batch.fetch.index_version, '4.3')
        self.assertEqual(len(batch.models), 10)
        model = batch.models[0]
        self.assertEqual(model.canonical_id,
                         '00000000-0000-4000-8000-000000000000')
        self.assertEqual(model.creator_name, 'Fixture Creator 00')
        # Free shape omits these; they are UNKNOWN, not "not supported".
        self.assertIsNone(model.modalities)
        self.assertIsNone(model.context_tokens)
        self.assertIsNone(model.model_family)
        self.assertEqual(model.as_dict()['modalities'], snapshot.UNKNOWN)
        self.assertEqual(model.pricing.input_per_mtok, 1.0)
        self.assertEqual(model.pricing.unit, snapshot.PRICE_UNIT)
        self.assertEqual(model.performance.output_tokens_per_second, 100.0)
        coding = model.evaluation('artificial_analysis_coding_index')
        self.assertEqual(coding.value, 10.0)
        self.assertEqual(coding.unit, 'index')
        self.assertEqual(coding.index_version, '4.3')
        self.assertEqual(coding.scope, 'composite')
        ifbench = model.evaluation('ifbench')
        self.assertEqual(ifbench.unit, 'proportion')
        self.assertIsNone(ifbench.index_version)
        self.assertIn('Free-shape', ' '.join(model.limitations))
        self.assertIn('not evidence that the model lacks the capability',
                      ' '.join(batch.models[0].limitations))

    def test_pro_shape_adds_modalities_context_and_per_benchmark_scores(self):
        with key():
            batch = fetch_one(payload=fixtures.payload(tier='pro'))
        model = batch.models[0]
        self.assertEqual(model.modalities, ('text', 'image'))
        self.assertEqual(model.context_tokens, 200000)
        self.assertEqual(model.reasoning_model, None)
        self.assertEqual(model.release_date, '2026-01-01')

    def test_request_uses_the_protected_key_header_and_no_query_secret(self):
        transport = fixtures.FakeTransport(
            [fixtures.json_response(fixtures.payload())])
        with key():
            fetch_one(transport=transport)
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request.header('x-api-key'), fixtures.API_KEY)
        self.assertNotIn(fixtures.API_KEY, request.url)
        # Even the request's diagnostic dict omits header values.
        self.assertNotIn(fixtures.API_KEY, str(request.as_dict()))

    def test_repr_never_contains_the_key(self):
        with key():
            source = fixtures.source(responses=[])
            text = repr(source)
        self.assertNotIn(fixtures.API_KEY, text)
        self.assertIn('key_present=True', text)

    def test_fetched_at_and_source_are_recorded(self):
        with key():
            batch = fetch_one()
        self.assertEqual(batch.models[0].fetched_at, fixtures.NOW)
        self.assertEqual(batch.models[0].source_id,
                         artificial_analysis.SOURCE_ID)
        self.assertEqual(batch.models[0].source_url,
                         artificial_analysis.DEFAULT_ENDPOINT)
        self.assertEqual(batch.models[0].freshness,
                         snapshot.FRESHNESS_FRESH)

    def test_unknown_evaluation_is_kept_as_unknown(self):
        rows = [fixtures.model_row(0, evaluations={
            'artificial_analysis_coding_index': None,
            'mystery_metric': 4.2,
        })]
        with key():
            batch = fetch_one(payload=fixtures.payload(rows=rows))
        model = batch.models[0]
        coding = model.evaluation('artificial_analysis_coding_index')
        self.assertFalse(coding.known)
        self.assertEqual(coding.as_dict()['value'], snapshot.UNKNOWN)
        mystery = model.evaluation('mystery_metric')
        self.assertEqual(mystery.unit, snapshot.UNKNOWN)
        self.assertEqual(mystery.value, 4.2)


class NoCredentialTests(unittest.TestCase):
    def test_missing_key_makes_no_request(self):
        transport = fixtures.FakeTransport([])
        with key(None):
            batch = fetch_one(transport=transport)
        self.assertEqual(batch.fetch.status, snapshot.FETCH_NO_CREDENTIAL)
        self.assertEqual(batch.fetch.requests, 0)
        self.assertEqual(batch.models, ())
        self.assertEqual(len(transport.requests), 0)
        self.assertIn('not a missing model capability',
                      ' '.join(batch.fetch.limitations))
        self.assertIn(KEY_ENV, batch.fetch.message)

    def test_empty_key_is_treated_as_missing(self):
        transport = fixtures.FakeTransport([])
        with key(''):
            batch = fetch_one(transport=transport)
        self.assertEqual(batch.fetch.status, snapshot.FETCH_NO_CREDENTIAL)
        self.assertEqual(len(transport.requests), 0)


class HttpFailureTests(unittest.TestCase):
    def _status(self, response):
        with key():
            return fetch_one(response=response)

    def test_401_is_authentication_failure(self):
        batch = self._status(fixtures.json_response(
            {'error': 'invalid key'}, status=401))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_AUTH_FAILED)
        self.assertEqual(batch.fetch.http_status, 401)
        self.assertFalse(batch.fetch.live)

    def test_403_is_a_tier_limit_not_a_capability_gap(self):
        batch = self._status(fixtures.json_response(
            {'error': 'subscription required'}, status=403))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_TIER_RESTRICTED)
        self.assertIn('tier limit', batch.fetch.message)
        self.assertNotIn('capability', batch.fetch.message.split('not evidence')[0])

    def test_429_records_retry_after(self):
        batch = self._status(fixtures.json_response(
            {'error': 'rate limit'}, status=429,
            headers=(('Retry-After', '3600'),)))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_RATE_LIMITED)
        self.assertEqual(batch.fetch.retry_after_seconds, 3600)
        self.assertIn('3600', batch.fetch.message)

    def test_500_is_a_server_error(self):
        batch = self._status(fixtures.raw_response('boom', status=500))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_SERVER_ERROR)

    def test_timeout_is_distinct_from_auth_and_schema(self):
        with key():
            batch = fetch_one(response=artificial_analysis.TransportTimeout(
                f'timed out with {fixtures.API_KEY}'))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_TIMEOUT)
        self.assertNotIn(fixtures.API_KEY, batch.fetch.message)
        self.assertIn('[REDACTED]', batch.fetch.message)

    def test_network_error_is_reported(self):
        with key():
            batch = fetch_one(response=artificial_analysis.TransportError(
                'network error: name resolution failed'))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_NETWORK_ERROR)


class SchemaTests(unittest.TestCase):
    def test_unparseable_body(self):
        with key():
            batch = fetch_one(response=fixtures.raw_response('<html>no</html>'))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_UNPARSEABLE)

    def test_missing_envelope_field_is_a_schema_change(self):
        for field in ('tier', 'intelligence_index_version', 'pagination', 'data'):
            with self.subTest(field=field):
                body = fixtures.payload()
                body.pop(field)
                with key():
                    batch = fetch_one(payload=body)
                self.assertEqual(batch.fetch.status,
                                 snapshot.FETCH_SCHEMA_CHANGED)
                self.assertIn(field, batch.fetch.message)

    def test_non_numeric_index_version_is_a_schema_change(self):
        body = fixtures.payload()
        body['intelligence_index_version'] = 'v4'
        with key():
            batch = fetch_one(payload=body)
        self.assertEqual(batch.fetch.status, snapshot.FETCH_SCHEMA_CHANGED)

    def test_one_bad_row_is_reported_and_good_rows_survive(self):
        rows = [fixtures.model_row(0), {'name': 'missing identity fields'}]
        with key():
            batch = fetch_one(payload=fixtures.payload(rows=rows))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_OK)
        self.assertEqual(len(batch.models), 1)
        self.assertTrue(any('row 1' in warning for warning in batch.warnings))

    def test_every_row_bad_is_a_schema_change(self):
        rows = [{'name': 'missing identity fields'}]
        with key():
            batch = fetch_one(payload=fixtures.payload(rows=rows))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_SCHEMA_CHANGED)
        self.assertIn('no model row', batch.fetch.message)

    def test_non_dict_evaluations_skips_only_that_row(self):
        row = fixtures.model_row(0)
        row['evaluations'] = 'not an object'
        good = fixtures.model_row(1)
        with key():
            batch = fetch_one(payload=fixtures.payload(rows=[row, good]))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_OK)
        self.assertEqual(len(batch.models), 1)

    def test_index_version_change_between_pages_is_refused(self):
        first = fixtures.json_response(fixtures.payload(
            rows=[fixtures.model_row(0)], has_more=True, total_pages=2))
        second = fixtures.json_response(fixtures.payload(
            rows=[fixtures.model_row(1)], version=4.4, page=2))
        with key():
            batch = fetch_one(transport=fixtures.FakeTransport([first, second]))
        self.assertEqual(batch.fetch.status, snapshot.FETCH_SCHEMA_CHANGED)
        self.assertIn('index_version', batch.fetch.message)
        self.assertEqual(batch.models, ())


class PaginationTests(unittest.TestCase):
    def test_two_pages_are_combined(self):
        first = fixtures.json_response(fixtures.payload(
            rows=[fixtures.model_row(0)], has_more=True, total_pages=2))
        second = fixtures.json_response(fixtures.payload(
            rows=[fixtures.model_row(1)], page=2))
        transport = fixtures.FakeTransport([first, second])
        with key():
            batch = fetch_one(transport=transport)
        self.assertEqual(batch.fetch.status, snapshot.FETCH_OK)
        self.assertEqual(len(batch.models), 2)
        self.assertEqual(batch.fetch.requests, 2)
        self.assertEqual(transport.requests[1].url,
                         fixtures.SOURCE_ENDPOINT + '?page=2')

    def test_pagination_limit_is_reported_as_partial(self):
        first = fixtures.json_response(fixtures.payload(
            rows=[fixtures.model_row(0)], has_more=True, total_pages=3))
        transport = fixtures.FakeTransport([first])
        with key():
            batch = fetch_one(transport=transport, max_pages=1)
        self.assertEqual(batch.fetch.status, snapshot.FETCH_OK)
        self.assertTrue(any('partial snapshot' in warning
                            for warning in batch.warnings))

    def test_duplicate_rows_across_pages_are_reported_and_deduplicated(self):
        row = fixtures.model_row(0)
        first = fixtures.json_response(fixtures.payload(
            rows=[row], has_more=True, total_pages=2))
        second = fixtures.json_response(fixtures.payload(rows=[row], page=2))
        with key():
            batch = fetch_one(transport=fixtures.FakeTransport([first, second]))
        self.assertEqual(len(batch.models), 1)
        self.assertTrue(any('duplicate' in warning for warning in batch.warnings))


class CacheFallbackTests(unittest.TestCase):
    def test_fresh_cache_is_used_after_a_rate_limit(self):
        store = fixtures.cache(max_age_seconds=24 * 60 * 60)
        with key():
            first = fetch_one(cache=store, now=fixtures.NOW)
            self.assertEqual(first.fetch.status, snapshot.FETCH_OK)
            second = fetch_one(
                response=fixtures.json_response({'error': 'rate limit'},
                                                status=429),
                cache=store, now=fixtures.LATER)
        self.assertEqual(second.fetch.status, snapshot.FETCH_CACHED)
        self.assertFalse(second.fetch.live)
        self.assertTrue(second.fetch.usable)
        self.assertTrue(second.fetch.used_cache)
        self.assertEqual(second.fetch.live_failure_status,
                         snapshot.FETCH_RATE_LIMITED)
        self.assertEqual(second.fetch.models_returned, 10)
        self.assertEqual(second.models[0].freshness,
                         snapshot.FRESHNESS_FRESH)
        self.assertIn('not a live', ' '.join(second.fetch.limitations))

    def test_expired_cache_is_stale_and_not_usable(self):
        store = fixtures.cache(max_age_seconds=60)
        with key():
            fetch_one(cache=store, now=fixtures.NOW)
            second = fetch_one(
                response=artificial_analysis.TransportTimeout('timed out'),
                cache=store, now=fixtures.EXPIRED)
        self.assertEqual(second.fetch.status, snapshot.FETCH_STALE_CACHE)
        self.assertFalse(second.fetch.live)
        self.assertFalse(second.fetch.usable)
        self.assertEqual(second.fetch.live_failure_status,
                         snapshot.FETCH_TIMEOUT)
        self.assertEqual(second.models[0].freshness,
                         snapshot.FRESHNESS_STALE)

    def test_schema_failure_does_not_overwrite_a_good_cache(self):
        store = fixtures.cache(max_age_seconds=24 * 60 * 60)
        with key():
            fetch_one(cache=store, now=fixtures.NOW)
            bad = fixtures.payload()
            bad.pop('data')
            second = fetch_one(payload=bad, cache=store, now=fixtures.LATER)
            third = fetch_one(cache=store, now=fixtures.LATER)
        self.assertEqual(second.fetch.status, snapshot.FETCH_CACHED)
        self.assertEqual(second.fetch.live_failure_status,
                         snapshot.FETCH_SCHEMA_CHANGED)
        self.assertEqual(third.fetch.status, snapshot.FETCH_OK)
        self.assertEqual(third.models[0].canonical_id,
                         second.models[0].canonical_id)

    def test_no_cache_and_no_key_is_not_reported_as_stale(self):
        with key(None):
            batch = fetch_one(cache=fixtures.cache())
        self.assertEqual(batch.fetch.status, snapshot.FETCH_NO_CREDENTIAL)
        self.assertFalse(batch.fetch.used_cache)


class EndpointContractTests(unittest.TestCase):
    def test_non_official_endpoint_is_refused(self):
        for endpoint in ('https://example.com/api/v2/language/models',
                         'http://artificialanalysis.ai/api/v2/language/models',
                         'https://artificialanalysis.ai/leaderboards/models'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(snapshot.SnapshotError):
                    fixtures.source(responses=[], endpoint=endpoint)

    def test_default_endpoint_is_the_documented_free_list(self):
        self.assertEqual(
            artificial_analysis.DEFAULT_ENDPOINT,
            'https://artificialanalysis.ai/api/v2/language/models/free')


if __name__ == '__main__':
    unittest.main()
