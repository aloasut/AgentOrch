"""Report conformance tests against the frozen update-report contract.

The validator is the engine's zero-dependency semantic check; these tests pin it
to the frozen fixtures in docs/contracts/fixtures (valid accepted, invalid
rejected) plus the semantic rules standard JSON Schema cannot express.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from update_agentorch import report as report_module

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'docs' / 'contracts' / 'fixtures'


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class ReportValidatorTests(unittest.TestCase):
    def setUp(self):
        self.valid = load('valid/update-report.valid.json')

    def errors(self, report: dict) -> list[str]:
        return report_module.validate_report(report)

    def test_frozen_valid_fixture_is_accepted(self):
        self.assertEqual(self.errors(self.valid), [])

    def test_frozen_invalid_fixtures_are_rejected(self):
        for name in ('invalid/update-report.applied-with-conflict.invalid.json',
                     'invalid/update-report.rollback-failed.invalid.json'):
            with self.subTest(name=name):
                self.assertTrue(self.errors(load(name)))

    def test_missing_required_section_is_rejected(self):
        for key in ('classification', 'target', 'baseline', 'backup', 'rollback',
                    'workspace', 'result', 'post_apply_checks'):
            with self.subTest(key=key):
                broken = copy.deepcopy(self.valid)
                del broken[key]
                self.assertTrue(self.errors(broken))

    def test_unknown_field_is_rejected(self):
        broken = copy.deepcopy(self.valid)
        broken['extra'] = True
        self.assertTrue(self.errors(broken))

    def test_counts_must_sum_to_files(self):
        broken = copy.deepcopy(self.valid)
        broken['classification']['counts']['ALREADY_CURRENT'] += 1
        self.assertTrue(any('count' in error.lower() for error in self.errors(broken)))

    def test_applied_requires_zero_conflicts(self):
        broken = copy.deepcopy(self.valid)
        broken['result'] = 'APPLIED'
        broken['operation']['mode'] = 'APPLY'
        broken['classification']['files'][0]['class'] = 'THREE_WAY_CONFLICT'
        broken['classification']['files'][0]['decision'] = 'CONFLICT_REPORTED'
        broken['classification']['counts']['UPSTREAM_UNCHANGED'] -= 1
        broken['classification']['counts']['THREE_WAY_CONFLICT'] += 1
        broken['backup'] = {'required': True, 'location': 'backup-dir',
                            'created_at': '2026-10-26T03:59:00Z', 'verified': True}
        broken['workspace']['action'] = 'ISOLATED_BRANCH'
        errors = self.errors(broken)
        self.assertTrue(any('conflict' in error.lower() for error in errors), errors)

    def test_applied_requires_verified_package_and_backup(self):
        broken = copy.deepcopy(self.valid)
        broken['result'] = 'APPLIED'
        broken['operation']['mode'] = 'APPLY'
        broken['backup'] = {'required': False, 'location': None,
                            'created_at': None, 'verified': False}
        broken['workspace']['action'] = 'ISOLATED_BRANCH'
        errors = self.errors(broken)
        self.assertTrue(any('backup' in error.lower() for error in errors), errors)

    def test_rollback_failed_must_be_blocked(self):
        broken = copy.deepcopy(self.valid)
        broken['rollback'] = {'required': True, 'attempted': True,
                              'result': 'FAILED', 'evidence': 'verification failed'}
        broken['result'] = 'ROLLED_BACK'
        self.assertTrue(any('rollback' in error.lower() for error in self.errors(broken)))

    def test_verified_package_cannot_have_not_run_or_failed_checks(self):
        for result_value in ('NOT_RUN', 'FAIL'):
            with self.subTest(result_value=result_value):
                broken = copy.deepcopy(self.valid)
                broken['target']['verification']['checks'][0]['result'] = result_value
                self.assertTrue(self.errors(broken))

    def test_unsafe_package_status_requires_a_failed_check(self):
        broken = copy.deepcopy(self.valid)
        broken['target']['verification']['status'] = 'UNSAFE_PACKAGE'
        self.assertTrue(self.errors(broken))

    def test_project_owned_and_unknown_can_never_be_applied(self):
        for klass in ('PROJECT_OWNED', 'UNKNOWN_FILE', 'UPSTREAM_REMOVAL',
                      'UPSTREAM_RENAME', 'THREE_WAY_CONFLICT'):
            with self.subTest(klass=klass):
                broken = copy.deepcopy(self.valid)
                broken['classification']['files'][0]['class'] = klass
                broken['classification']['files'][0]['decision'] = 'APPLIED'
                self.assertTrue(self.errors(broken))

    def test_dirty_workspace_contract(self):
        broken = copy.deepcopy(self.valid)
        broken['workspace'] = {'dirty': True, 'dirty_paths': [], 'action': 'NONE'}
        self.assertTrue(self.errors(broken))

        broken = copy.deepcopy(self.valid)
        broken['workspace'] = {'dirty': False, 'dirty_paths': [],
                               'action': 'STOPPED_DIRTY_WORKTREE'}
        self.assertTrue(self.errors(broken))

    def test_invalid_baseline_requires_a_stopped_result(self):
        broken = copy.deepcopy(self.valid)
        broken['baseline']['baseline_status'] = 'INVALID_BASELINE'
        broken['result'] = 'APPLIED'
        broken['operation']['mode'] = 'APPLY'
        self.assertTrue(self.errors(broken))

    def test_release_tag_and_version_must_normalize_together(self):
        broken = copy.deepcopy(self.valid)
        broken['target']['version'] = '1.7.0'
        self.assertTrue(any('version' in error.lower() for error in self.errors(broken)))

    def test_report_id_shape(self):
        broken = copy.deepcopy(self.valid)
        broken['report_id'] = 'not-a-report-id'
        self.assertTrue(self.errors(broken))

    def test_applied_cannot_carry_open_human_decisions(self):
        broken = copy.deepcopy(self.valid)
        broken['result'] = 'APPLIED'
        broken['operation']['mode'] = 'APPLY'
        broken['backup'] = {'required': True, 'location': 'backup-dir',
                            'created_at': '2026-10-26T03:59:00Z', 'verified': True}
        broken['workspace']['action'] = 'ISOLATED_BRANCH'
        broken['classification']['counts']['UPSTREAM_UNCHANGED'] = 2
        broken['classification']['counts']['PROJECT_OWNED'] = 0
        broken['classification']['files'][1]['class'] = 'UPSTREAM_UNCHANGED'
        broken['classification']['files'][1]['decision'] = 'APPLIED'
        broken['classification']['files'][1]['baseline_sha256'] = 'd' * 64
        broken['classification']['files'][1]['current_sha256'] = 'd' * 64
        broken['classification']['files'][1]['target_sha256'] = 'e' * 64
        broken['human_decisions'] = [{'decision_id': 'HD-10', 'question': 'Which side wins?',
                                      'options': ['local', 'upstream'], 'status': 'OPEN'}]
        self.assertTrue(any('human' in error.lower() or 'decision' in error.lower()
                            for error in self.errors(broken)))


if __name__ == '__main__':
    unittest.main()
