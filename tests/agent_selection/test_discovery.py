"""Discovery with explicit-registry fallback tests (#121, design §5.1).

All registries are throwaway temporary stores or in-memory fixtures; no real
``.local`` directory, runtime or network is touched.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection import discovery, local_store, runtime_adapter  # noqa: E402
from tests.agent_selection import support  # noqa: E402

NOW = support.NOW


def registry_entry(**overrides):
    kwargs = {'source': 'explicit-registry'}
    kwargs.update(overrides)
    return support.candidate(**kwargs)


def registry_record(*, agent_id='exec-1', model_id='model-a',
                    capability_ref='cap-1', **extra):
    details = {
        'runtime_id': 'fixture-runtime',
        'runtime_version': '1.0.0',
        'agent_id': agent_id,
        'model_id': model_id,
        'model_family': 'family-a',
        'modalities': 'text',
        'tools': 'file-read,file-write,command',
        'read_paths': 'src',
        'write_paths': 'src',
        'commands': 'python',
        'network': 'false',
        'read_only': 'false',
        'context_tokens': '200000',
        'cost_per_mtok': '1.0',
        'latency_ms': '1000',
        'capability_ref': capability_ref,
        'evidence_time': NOW,
        'source_class': 'OBSERVED',
    }
    details.update(extra)
    return details


class RuntimeFirstTests(unittest.TestCase):
    def test_runtime_enumeration_wins_over_the_registry(self):
        runtime_candidate = registry_entry(agent_id='runtime-agent',
                                           source='runtime-discovery')
        registry_candidate = registry_entry(agent_id='registry-agent')
        report = discovery.discover_candidates(
            adapter=support.FixtureAdapter(support.ok_result([runtime_candidate])),
            registry=discovery.ExplicitRegistry(entries=(registry_candidate,)))
        self.assertEqual(report.outcome, discovery.DISCOVERY_RUNTIME)
        self.assertEqual([c.agent_id for c in report.candidates],
                         ['runtime-agent'])
        self.assertIsNotNone(report.runtime_result)

    def test_registry_entries_are_returned_unchanged(self):
        entry = registry_entry()
        report = discovery.discover_candidates(
            adapter=support.FixtureAdapter(
                runtime_adapter.DiscoveryResult(
                    outcome='UNSUPPORTED', mode='runtime')),
            registry=discovery.ExplicitRegistry(entries=(entry,)))
        self.assertEqual(report.outcome, discovery.DISCOVERY_REGISTRY)
        self.assertIs(report.candidates[0], entry)
        self.assertEqual(report.source, 'explicit-registry')

    def test_no_adapter_and_no_registry_reports_no_adapter(self):
        report = discovery.discover_candidates()
        self.assertEqual(report.outcome, discovery.DISCOVERY_NO_ADAPTER)
        self.assertEqual(report.candidates, ())
        self.assertFalse(report.discovered)
        self.assertIn('no agent is invented', ' '.join(report.notes))

    def test_empty_runtime_without_registry_reports_empty(self):
        report = discovery.discover_candidates(adapter=support.FixtureAdapter(
            runtime_adapter.DiscoveryResult(outcome='EMPTY', mode='runtime')))
        self.assertEqual(report.outcome, discovery.DISCOVERY_EMPTY)
        self.assertEqual(report.candidates, ())

    def test_adapter_failure_is_reported_not_hidden(self):
        class BrokenAdapter(runtime_adapter.RuntimeAdapter):
            def describe(self):
                raise RuntimeError('adapter exploded')

            def discover(self):  # pragma: no cover - describe fails first
                raise RuntimeError('adapter exploded')

        report = discovery.discover_candidates(adapter=BrokenAdapter())
        self.assertEqual(report.outcome, discovery.DISCOVERY_ERROR)
        self.assertEqual(report.candidates, ())
        self.assertIn('adapter exploded', ' '.join(report.notes))

    def test_unsupported_runtime_and_empty_registry_reports_no_adapter(self):
        report = discovery.discover_candidates(
            adapter=runtime_adapter.HostOpaqueRuntimeAdapter(
                runtime_id='process-local', runtime_version='0.0.0',
                edition='github'),
            registry=discovery.ExplicitRegistry())
        self.assertEqual(report.outcome, discovery.DISCOVERY_NO_ADAPTER)
        self.assertEqual(report.candidates, ())
        self.assertIn('does not expose a formal agent enumeration',
                      ' '.join(report.notes))


class ExplicitRegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = local_store.LocalStore(Path(self._tmp.name), 'scope-1')
        self.store.initialize()
        self.capabilities = {'cap-1': support.capability_record()}

    def append(self, details, *, summary='agent entry', status='RECORDED'):
        return self.store.append_record('agent-registry.md', summary=summary,
                                        status=status, details=details)

    def test_valid_record_becomes_a_candidate(self):
        self.append(registry_record())
        registry = discovery.ExplicitRegistry.from_store(
            self.store, capability_records=self.capabilities)
        self.assertEqual(registry.issues, ())
        self.assertEqual(len(registry.entries), 1)
        entry = registry.entries[0]
        self.assertEqual(entry.agent_id, 'exec-1')
        self.assertEqual(entry.source, 'explicit-registry')
        self.assertEqual(entry.permissions.write_paths, ('src',))
        self.assertIsNotNone(entry.capability_record)
        result = registry.discover()
        self.assertEqual(result.outcome, 'OK')
        self.assertEqual(result.mode, 'explicit-registry')

    def test_unknown_capability_ref_keeps_the_candidate_without_evidence(self):
        self.append(registry_record(capability_ref='missing-cap'))
        registry = discovery.ExplicitRegistry.from_store(self.store)
        self.assertEqual(len(registry.entries), 1)
        self.assertIsNone(registry.entries[0].capability_record)
        self.assertIn('capability record', ' '.join(registry.issues))

    def test_record_missing_a_required_field_is_skipped(self):
        details = registry_record()
        del details['model_id']
        self.append(details)
        registry = discovery.ExplicitRegistry.from_store(self.store)
        self.assertEqual(registry.entries, ())
        self.assertIn('missing model_id', ' '.join(registry.issues))

    def test_record_without_source_class_is_not_a_candidate(self):
        details = registry_record()
        del details['source_class']
        self.append(details)
        registry = discovery.ExplicitRegistry.from_store(
            self.store, capability_records=self.capabilities)
        self.assertEqual(registry.entries, ())
        self.assertIn('missing source_class', ' '.join(registry.issues))
        self.assertEqual(registry.discover().outcome, 'EMPTY')

    def test_unexpected_detail_key_is_not_guessed(self):
        self.append(registry_record(prompt_name='execution'))
        registry = discovery.ExplicitRegistry.from_store(self.store)
        self.assertEqual(registry.entries, ())
        self.assertIn('unsupported detail key', ' '.join(registry.issues))

    def test_superseded_record_is_not_resurrected(self):
        self.append(registry_record(), status='SUPERSEDED')
        registry = discovery.ExplicitRegistry.from_store(
            self.store, capability_records=self.capabilities)
        self.assertEqual(registry.entries, ())
        self.assertEqual(registry.discover().outcome, 'EMPTY')

    def test_registry_fallback_is_used_when_the_runtime_cannot_enumerate(self):
        self.append(registry_record())
        registry = discovery.ExplicitRegistry.from_store(
            self.store, capability_records=self.capabilities)
        report = discovery.discover_candidates(
            adapter=runtime_adapter.HostOpaqueRuntimeAdapter(
                runtime_id='process-local', runtime_version='0.0.0',
                edition='github'),
            registry=registry)
        self.assertEqual(report.outcome, discovery.DISCOVERY_REGISTRY)
        self.assertEqual(len(report.candidates), 1)
        self.assertIn('explicit registry was used', ' '.join(report.notes))


if __name__ == '__main__':
    unittest.main()
