"""Runtime adapter contract tests (#121, design §4–§5).

Fixed fixtures only: no runtime process, no network, no real model data.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection import runtime_adapter  # noqa: E402
from tests.agent_selection import support  # noqa: E402

NOW = support.NOW


class CapabilityValidationTests(unittest.TestCase):
    def test_pass_requires_observed_evidence_with_a_reference(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.Capability('C1', 'PASS', source_class='INFERRED',
                                       probe_date=support.PROBE,
                                       evidence_ref='probe:1')
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.Capability('C1', 'PASS', source_class='OBSERVED',
                                       probe_date=support.PROBE)
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.Capability('C1', 'PASS', source_class='OBSERVED',
                                       evidence_ref='probe:1')

    def test_unknown_and_fail_never_need_evidence(self):
        for verdict in ('UNKNOWN', 'FAIL', 'NOT_APPLICABLE'):
            with self.subTest(verdict=verdict):
                row = runtime_adapter.Capability('C1', verdict)
                self.assertEqual(row.verdict, verdict)

    def test_unknown_capability_id_is_rejected(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.Capability('C9', 'UNKNOWN')


class CapabilityGateTests(unittest.TestCase):
    def gate(self, record):
        return record.gate(now=NOW, max_age_days=30)

    def test_all_c1_to_c4_pass_opens_the_path(self):
        gate = self.gate(support.capability_record())
        self.assertTrue(gate.passed)
        self.assertEqual(gate.status, 'PASS')

    def test_c1_failure_blocks_the_path(self):
        record = support.capability_record(overrides={
            'C1': support.capability('C1', 'FAIL', evidence_ref='')})
        gate = self.gate(record)
        self.assertEqual(gate.status, 'BLOCKED')
        self.assertIn('C1: FAIL', ' '.join(gate.reasons))

    def test_c2_context_isolation_failure_blocks_the_path(self):
        record = support.capability_record(overrides={
            'C2': support.capability(
                'C2', 'FAIL', evidence_ref='',
                limits='two probes shared one writable session')})
        gate = self.gate(record)
        self.assertEqual(gate.status, 'BLOCKED')
        self.assertIn('C2', ' '.join(gate.reasons))

    def test_c3_empty_result_is_not_success(self):
        record = support.capability_record(overrides={
            'C3': support.capability(
                'C3', 'FAIL', evidence_ref='',
                limits='wait returned an empty result that could not be '
                       'classified')})
        gate = self.gate(record)
        self.assertEqual(gate.status, 'BLOCKED')
        self.assertFalse(gate.passed)

    def test_unknown_row_cannot_be_counted_as_pass(self):
        record = support.capability_record(overrides={
            'C4': support.capability('C4', 'UNKNOWN', probe_date=None)})
        self.assertEqual(self.gate(record).status, 'UNKNOWN')

    def test_missing_row_is_unknown_not_pass(self):
        record = support.capability_record()
        rows = tuple(row for row in record.capabilities
                     if row.capability_id != 'C2')
        without = runtime_adapter.CapabilityRecord(
            runtime_id=record.runtime_id, runtime_version=record.runtime_version,
            edition=record.edition, execution_mode=record.execution_mode,
            status=record.status, probe_date=record.probe_date,
            evidence_ref=record.evidence_ref, capabilities=rows)
        gate = self.gate(without)
        self.assertEqual(gate.status, 'UNKNOWN')
        self.assertIn('C2', gate.missing)

    def test_partial_and_stale_records_never_unlock(self):
        for status in ('PARTIAL', 'STALE'):
            with self.subTest(status=status):
                gate = self.gate(support.capability_record(status=status))
                self.assertEqual(gate.status, 'BLOCKED')

    def test_stale_probe_is_downgraded(self):
        record = support.capability_record(probe_date=support.OLD_PROBE)
        gate = self.gate(record)
        self.assertEqual(gate.status, 'BLOCKED')
        self.assertTrue(gate.stale)
        self.assertIn('re-probe', ' '.join(gate.reasons))

    def test_stale_row_evidence_is_blocked(self):
        stale_row = runtime_adapter.Capability(
            'C4', 'UNKNOWN', source_class='STALE',
            probe_date=support.PROBE, evidence_ref='probe:old')
        record = support.capability_record(overrides={'C4': stale_row})
        gate = self.gate(record)
        self.assertEqual(gate.status, 'BLOCKED')
        self.assertTrue(gate.stale)


class AdapterContractTests(unittest.TestCase):
    def test_host_opaque_adapter_reports_unsupported_and_no_candidates(self):
        adapter = runtime_adapter.HostOpaqueRuntimeAdapter(
            runtime_id='process-local', runtime_version='0.0.0', edition='github')
        description = adapter.describe()
        self.assertFalse(description.can_enumerate_agents)
        result = adapter.discover()
        self.assertEqual(result.outcome, 'UNSUPPORTED')
        self.assertEqual(result.candidates, ())
        self.assertIn('process-local', ' '.join(description.notes))

    def test_discovery_result_rejects_ok_without_candidates(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.DiscoveryResult(outcome='OK', mode='runtime')

    def test_candidate_requires_a_matching_capability_record(self):
        other = support.capability_record(runtime_id='other-runtime')
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            support.candidate(capability_record_value=other)

    def test_read_only_scope_cannot_declare_write_paths(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.PermissionScope(read_only=True, write_paths=('src',))


class PathAndEvidenceHelperTests(unittest.TestCase):
    def test_covers_path_is_component_aware(self):
        self.assertTrue(runtime_adapter.covers_path(('docs',), 'docs/a.md'))
        self.assertTrue(runtime_adapter.covers_path(('./docs/',), 'docs/a.md'))
        self.assertFalse(runtime_adapter.covers_path(('docs',), 'docs-other/a.md'))
        self.assertFalse(runtime_adapter.covers_path(('docs',), 'src/a.py'))
        self.assertFalse(runtime_adapter.covers_path((), 'docs/a.md'))

    def test_covers_command_is_exact_or_explicit_wildcard(self):
        self.assertTrue(runtime_adapter.covers_command(('python',), 'python'))
        self.assertFalse(runtime_adapter.covers_command(('python',), 'python3'))
        self.assertTrue(runtime_adapter.covers_command(('*',), 'python3'))
        self.assertFalse(runtime_adapter.covers_command((), 'python'))

    def test_covers_command_ignores_blank_entries(self):
        self.assertFalse(runtime_adapter.covers_command(('',), 'python'))
        self.assertFalse(runtime_adapter.covers_command(('   ',), 'python'))
        self.assertFalse(runtime_adapter.covers_command(('', '   '), 'python'))
        self.assertTrue(runtime_adapter.covers_command(('*',), 'python3'))

    def test_permission_scope_rejects_blank_command_entries(self):
        for commands in (('',), ('   ',), ('python', '')):
            with self.subTest(commands=commands):
                with self.assertRaises(runtime_adapter.RuntimeAdapterError):
                    runtime_adapter.PermissionScope(commands=commands)

    def test_network_enabled_cannot_be_observed_off(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.PermissionScope(network=True, network_observed=False)

    def test_network_disabled_cannot_be_observed_on(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.PermissionScope(network=False, network_observed=True)

    def test_evidence_age_uses_the_supplied_now(self):
        self.assertAlmostEqual(
            runtime_adapter.evidence_age_days(support.PROBE, NOW), 1.0)
        self.assertIsNone(runtime_adapter.evidence_age_days('not-a-date', NOW))

    def test_timestamp_format_is_enforced(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.parse_timestamp('2026-10-27 12:00:00')

    def test_graded_role_evidence_cannot_be_inferred(self):
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.RoleEvidence(
                role='reviewer', dimension='defect-detection', grade='STRONG',
                origin='project', evidence_ref='fixture', observed_at=NOW,
                sample_size=5, source_class='INFERRED')
        with self.assertRaises(runtime_adapter.RuntimeAdapterError):
            runtime_adapter.RoleEvidence(
                role='reviewer', dimension='defect-detection', grade='STRONG',
                origin='project', evidence_ref='fixture', observed_at=NOW,
                sample_size=0)


if __name__ == '__main__':
    unittest.main()
