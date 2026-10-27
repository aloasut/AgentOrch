"""Vendor-neutral snapshot / freshness / cache tests (#122, S3).

All data is synthetic. No network, no API key and no ``.local`` directory is
used. The focus is the honesty rules: missing is UNKNOWN, a cache never claims
to be live, and an expired reading is STALE.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection.model_sources import snapshot  # noqa: E402
from tests.agent_selection.model_sources import fixtures  # noqa: E402

NOW = fixtures.NOW


def make_snapshot(**overrides):
    values = dict(
        canonical_id='canonical-1', name='Fixture Model', slug='fixture-model',
        source_id='fixture-source', source_url='https://example.invalid/api',
        fetched_at=NOW, creator_name='Fixture Creator',
        freshness=snapshot.FRESHNESS_FRESH,
    )
    values.update(overrides)
    return snapshot.ModelSnapshot(**values)


def make_fetch(**overrides):
    values = dict(
        source_id='fixture-source', source_url='https://example.invalid/api',
        status=snapshot.FETCH_OK, fetched_at=NOW, http_status=200,
    )
    values.update(overrides)
    return snapshot.FetchRecord(**values)


def make_batch(models=(), fetch=None, warnings=()):
    return snapshot.SnapshotBatch(
        source_id='fixture-source', fetch=fetch or make_fetch(),
        models=tuple(models), warnings=tuple(warnings))


class MissingFieldTests(unittest.TestCase):
    def test_absent_fields_render_as_unknown_not_zero(self):
        model = make_snapshot()
        payload = model.as_dict()
        self.assertEqual(payload['model_family'], snapshot.UNKNOWN)
        self.assertEqual(payload['modalities'], snapshot.UNKNOWN)
        self.assertEqual(payload['context_tokens'], snapshot.UNKNOWN)
        self.assertEqual(payload['release_date'], snapshot.UNKNOWN)
        self.assertEqual(payload['pricing'], snapshot.UNKNOWN)
        self.assertEqual(payload['performance'], snapshot.UNKNOWN)
        self.assertEqual(payload['reasoning_model'], snapshot.UNKNOWN)
        self.assertFalse(model.family_known)

    def test_zero_is_a_measured_value_not_unknown(self):
        model = make_snapshot(
            pricing=snapshot.ModelPricing(input_per_mtok=0.0),
            performance=snapshot.ModelPerformance(
                output_tokens_per_second=0.0))
        payload = model.as_dict()
        self.assertEqual(payload['pricing']['input_per_mtok'], 0.0)
        self.assertEqual(
            payload['performance']['output_tokens_per_second'], 0.0)

    def test_null_evaluation_stays_unknown(self):
        evaluation = snapshot.ModelEvaluation(name='coding_index', value=None,
                                              unit='index')
        self.assertFalse(evaluation.known)
        self.assertEqual(evaluation.as_dict()['value'], snapshot.UNKNOWN)

    def test_negative_composite_index_is_allowed(self):
        evaluation = snapshot.ModelEvaluation(
            name='omniscience_index', value=-63.92, unit='index')
        self.assertTrue(evaluation.known)

    def test_string_price_is_rejected_instead_of_coerced(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.ModelPricing(input_per_mtok='1.0')

    def test_duplicate_evaluation_name_is_rejected(self):
        evaluation = snapshot.ModelEvaluation(name='coding', value=1.0)
        with self.assertRaises(snapshot.SnapshotError):
            make_snapshot(evaluations=(evaluation, evaluation))

    def test_invalid_context_tokens_is_rejected(self):
        with self.assertRaises(snapshot.SnapshotError):
            make_snapshot(context_tokens=0)

    def test_exact_identity_match_only(self):
        model = make_snapshot(canonical_id='id-1', slug='slug-1',
                              name='A Very Similar Name')
        self.assertTrue(model.matches('id-1'))
        self.assertTrue(model.matches('slug-1'))
        self.assertFalse(model.matches('A Very Similar Name'))
        self.assertFalse(model.matches('id-'))


class FreshnessTests(unittest.TestCase):
    def test_freshness_boundary(self):
        self.assertEqual(
            snapshot.freshness_for_age(10, 10), snapshot.FRESHNESS_FRESH)
        self.assertEqual(
            snapshot.freshness_for_age(11, 10), snapshot.FRESHNESS_STALE)
        self.assertEqual(
            snapshot.freshness_for_age(None, 10), snapshot.FRESHNESS_UNKNOWN)

    def test_fetch_record_never_calls_cache_live(self):
        cached = make_fetch(status=snapshot.FETCH_CACHED, used_cache=True,
                            cache_age_seconds=10, max_age_seconds=100)
        stale = make_fetch(status=snapshot.FETCH_STALE_CACHE, used_cache=True,
                           cache_age_seconds=200, max_age_seconds=100)
        self.assertFalse(cached.live)
        self.assertTrue(cached.usable)
        self.assertEqual(cached.freshness, snapshot.FRESHNESS_FRESH)
        self.assertFalse(stale.live)
        self.assertFalse(stale.usable)
        self.assertEqual(stale.freshness, snapshot.FRESHNESS_STALE)

    def test_cache_status_requires_used_cache(self):
        with self.assertRaises(snapshot.SnapshotError):
            make_fetch(status=snapshot.FETCH_CACHED)

    def test_live_failure_status_requires_a_cache_read(self):
        with self.assertRaises(snapshot.SnapshotError):
            make_fetch(live_failure_status=snapshot.FETCH_RATE_LIMITED)
        with self.assertRaises(snapshot.SnapshotError):
            make_fetch(status=snapshot.FETCH_CACHED, used_cache=True,
                       live_failure_status=snapshot.FETCH_OK)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.model = make_snapshot()
        self.batch = make_batch([self.model])

    def test_only_a_successful_live_fetch_can_be_cached(self):
        store = snapshot.SnapshotCache(max_age_seconds=100)
        store.store('key', self.batch, now=NOW)
        failed = make_batch(
            [], fetch=make_fetch(status=snapshot.FETCH_RATE_LIMITED))
        with self.assertRaises(snapshot.SnapshotError):
            store.store('key', failed, now=NOW)

    def test_fresh_and_expired_cache_hits(self):
        store = snapshot.SnapshotCache(max_age_seconds=3600)
        store.store('key', self.batch, now=NOW)
        fresh = store.load('key', now=fixtures.LATER)
        self.assertTrue(fresh.fresh)
        self.assertAlmostEqual(fresh.age_seconds, 3600, places=0)
        expired = store.load('key', now=fixtures.EXPIRED)
        self.assertFalse(expired.fresh)
        self.assertGreater(expired.age_seconds, 3600)
        self.assertIsNone(store.load('other', now=NOW))

    def test_stale_batch_marks_models_stale_and_keeps_data_time(self):
        store = snapshot.SnapshotCache(max_age_seconds=10)
        store.store('key', self.batch, now=NOW)
        hit = store.load('key', now=fixtures.EXPIRED)
        batch = snapshot.stale_batch(
            hit.entry.batch, status=snapshot.FETCH_STALE_CACHE,
            message='expired', now=fixtures.EXPIRED,
            cache_age_seconds=hit.age_seconds, max_age_seconds=10,
            live_failure_status=snapshot.FETCH_TIMEOUT)
        self.assertEqual(batch.fetch.status, snapshot.FETCH_STALE_CACHE)
        self.assertFalse(batch.fetch.live)
        self.assertFalse(batch.fetch.usable)
        self.assertEqual(batch.fetch.live_failure_status,
                         snapshot.FETCH_TIMEOUT)
        self.assertEqual(batch.models[0].freshness, snapshot.FRESHNESS_STALE)
        # The data time is the original fetch, not the cache read time.
        self.assertEqual(batch.models[0].fetched_at, NOW)
        self.assertIn('STALE', ' '.join(batch.fetch.limitations))

    def test_stale_batch_refuses_non_cache_status(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.stale_batch(self.batch, status=snapshot.FETCH_OK,
                                 message='not a cache', now=NOW)


if __name__ == '__main__':
    unittest.main()
