"""Structural tests for scripts/validate_kit.py (evidence matrix contract).

The field names / status enum are read back from AGENT-ORCHESTRATION.md, so these
tests fail if the authoritative definition and the validator drift apart.
"""
import importlib.util, re, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'validate_kit.py'
spec = importlib.util.spec_from_file_location('validate_kit', SCRIPT)
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

ROOT = SCRIPT.parents[1]
HEAD = 'a' * 40


def canonical():
    core = (ROOT / validate.CORE_DOC).read_text(encoding='utf-8')
    return validate.canonical_evidence_fields(core)


class TaskPacketMatrixTests(unittest.TestCase):
    def setUp(self):
        self.evidence_fields, self.status_values = canonical()
        self.structured = validate.canonical_packet_fields(
            (ROOT / validate.CORE_DOC).read_text(encoding='utf-8'))

    # --- builders -----------------------------------------------------------
    def header(self):
        return '| ' + ' | '.join(self.evidence_fields) + ' |'

    def row(self, ac='AC-1', status='PASS', actual='3 tests passed', sha=HEAD,
            notes='(none)', ref='task record: evidence log 1'):
        cells = {
            'ac_id': ac,
            'method': '`python -m unittest`',
            'expected': 'tests pass',
            'actual': actual,
            'status': status,
            'environment': 'Linux, Python 3.12, local edition',
            'commit_sha': sha,
            'evidence_ref': ref,
            'notes': notes,
        }
        return '  | ' + ' | '.join(cells[name] for name in self.evidence_fields) + ' |'

    def packet(self, acs=None, rows=None, structured=None, head=HEAD, omit=(), resources=None):
        acs = acs if acs is not None else [('x', 'AC-1', 'dry run writes nothing'),
                                           ('x', 'AC-2', 'existing behaviour unchanged')]
        rows = rows if rows is not None else [self.row('AC-1'), self.row('AC-2', actual='12 tests passed')]
        structured = structured if structured is not None else {
            name: 'N/A: covered by the criteria above' for name in self.structured}
        lines = []
        skipped = {validate.field_label(name) for name in omit}

        def add(label, value=''):
            if validate.field_label(label) in skipped:
                return
            lines.append(f'- **{label}:**' + (f' {value}' if value else ''))

        add('Task ID', 'SAMPLE-9001')
        add('Title', 'Add a dry-run flag')
        add('Goal / user-visible result', 'the export command can report without writing')
        add('Context', 'single command, no persisted state')
        add('Allowed paths', '`src/cli/export.py`')
        add('Forbidden paths', 'every other path in the repository')
        # `resources=None` means "field absent"; '' means "field present but empty".
        if resources is not None:
            add('declared_resources', resources)
        add('Dependencies (must be VERIFIED)', 'none')
        add('Acceptance criteria')
        for mark, ac_id, text in acs:
            lines.append(f'  - [{mark}] {ac_id}: {text}')
        for name in self.structured:
            add(name, structured.get(name, ''))
        add('Validation commands', '`python -m unittest`')
        add('Baseline branch / commit', '`main` @ `1111111`')
        add('Expected branch / Worktree', '`task/9001-dry-run` / `.worktrees/9001-dry-run`')
        add('Evidence head SHA', head)
        add('Evidence matrix')
        if 'evidence matrix' not in omit:
            lines.append(f'  {self.header()}')
            lines.append('  |' + '---|' * len(self.evidence_fields))
            lines.extend(rows)
        add('Risks / human decisions', 'none identified')
        add('Delivery evidence', 'changed paths, Diff, head SHA, exit codes')
        add('Hard boundaries', 'no scope expansion, no self-approval, no merge')
        return '\n'.join(lines) + '\n'

    def errors(self, text):
        return validate.validate_task_packet(text, self.evidence_fields, self.status_values,
                                             label='packet', structured_fields=self.structured)

    # --- contract extraction ------------------------------------------------
    def test_canonical_fields_are_read_from_the_core_document(self):
        self.assertEqual(self.evidence_fields, [
            'ac_id', 'method', 'expected', 'actual', 'status',
            'environment', 'commit_sha', 'evidence_ref', 'notes',
        ])
        self.assertEqual(set(self.status_values), set(validate.STATUS_VALUES))
        self.assertEqual(self.structured, [
            'invariants', 'negative_cases', 'migration_cases',
            'integration_paths', 'unverified_assumptions',
        ])

    # --- legal packets ------------------------------------------------------
    def test_legal_packet_passes(self):
        self.assertEqual(self.errors(self.packet()), [])

    def test_legal_packet_with_not_applicable_evidence_passes(self):
        acs = [('x', 'AC-1', 'dry run writes nothing'),
               (' ', 'AC-2', 'only applies when a remote target is configured')]
        rows = [self.row('AC-1'),
                self.row('AC-2', status='NOT_APPLICABLE', actual='n/a', sha='(none)',
                         notes='the flag cannot affect this path')]
        self.assertEqual(self.errors(self.packet(acs=acs, rows=rows)), [])

    def test_legal_packet_with_unchecked_criterion_and_not_run_passes(self):
        acs = [('x', 'AC-1', 'migration fills defaults'), (' ', 'AC-2', 'v1 saves migrate too')]
        rows = [self.row('AC-1'),
                self.row('AC-2', status='NOT_RUN', actual='not executed: fixture missing',
                         ref='task record: no run recorded')]
        self.assertEqual(self.errors(self.packet(acs=acs, rows=rows)), [])

    # --- missing / empty required content -----------------------------------
    def test_missing_structured_field_is_reported(self):
        errors = self.errors(self.packet(omit=('negative_cases',)))
        self.assertTrue(any('missing structured field: negative_cases' in e for e in errors), errors)

    def test_missing_required_field_is_reported(self):
        errors = self.errors(self.packet(omit=('allowed paths',)))
        self.assertTrue(any('missing required field: allowed paths' in e for e in errors), errors)

    def test_empty_required_field_is_reported(self):
        errors = self.errors(self.packet().replace('- **Title:** Add a dry-run flag', '- **Title:**'))
        self.assertTrue(any('required field is empty: title' in e for e in errors), errors)

    def test_bare_na_without_reason_is_reported(self):
        errors = self.errors(self.packet(structured={'negative_cases': 'N/A'}))
        self.assertTrue(any('must give a reason after "N/A:"' in e for e in errors), errors)

    def test_empty_acceptance_criterion_is_reported(self):
        acs = [('x', 'AC-1', '')]
        errors = self.errors(self.packet(acs=acs, rows=[self.row('AC-1')]))
        self.assertTrue(any('has no checkable statement' in e for e in errors), errors)

    def test_acceptance_criterion_without_id_is_reported(self):
        errors = self.errors(self.packet().replace('  - [x] AC-1:', '  - [x] '))
        self.assertTrue(any('without an AC-<n> id' in e for e in errors), errors)

    def test_duplicate_acceptance_id_is_reported(self):
        acs = [('x', 'AC-1', 'one'), ('x', 'AC-1', 'two')]
        errors = self.errors(self.packet(acs=acs, rows=[self.row('AC-1')]))
        self.assertTrue(any('duplicate acceptance criterion id: AC-1' in e for e in errors), errors)

    # --- evidence mapping ---------------------------------------------------
    def test_acceptance_criterion_without_evidence_is_reported(self):
        acs = [('x', 'AC-1', 'first'), ('x', 'AC-2', 'second')]
        errors = self.errors(self.packet(acs=acs, rows=[self.row('AC-1'), self.row('AC-9')]))
        self.assertTrue(any('AC-2 has no evidence item' in e for e in errors), errors)
        self.assertTrue(any('references unknown acceptance criterion: AC-9' in e for e in errors), errors)

    def test_matrix_without_rows_is_reported(self):
        errors = self.errors(self.packet(rows=[]))
        self.assertTrue(any('has no evidence items' in e for e in errors), errors)

    def test_wrong_matrix_columns_are_reported(self):
        text = self.packet()
        text = text.replace(self.header(), '| ac_id | status |')
        self.assertTrue(any('columns must be exactly' in e for e in self.errors(text)))

    def test_evidence_item_with_missing_field_is_reported(self):
        rows = [self.row('AC-1').replace(' | (none) |', ' |'), self.row('AC-2')]
        errors = self.errors(self.packet(rows=rows))
        self.assertTrue(any('fields, expected' in e for e in errors), errors)

    # --- "not executed" must not become "passing" ---------------------------
    def test_not_run_cannot_satisfy_a_checked_criterion(self):
        rows = [self.row('AC-1'),
                self.row('AC-2', status='NOT_RUN', actual='not executed')]
        errors = self.errors(self.packet(rows=rows))
        self.assertTrue(any('AC-2 is marked as met but has NOT_RUN evidence' in e for e in errors), errors)

    def test_pass_status_with_not_run_text_is_reported(self):
        for phrasing in ('not run: environment missing', 'not executed: fixture missing'):
            with self.subTest(actual=phrasing):
                rows = [self.row('AC-1', actual=phrasing), self.row('AC-2')]
                errors = self.errors(self.packet(rows=rows))
                self.assertTrue(any('is PASS but reports not-run' in e for e in errors), errors)

    def test_unknown_status_is_reported(self):
        rows = [self.row('AC-1', status='OK'), self.row('AC-2')]
        self.assertTrue(any('unknown status: OK' in e for e in self.errors(self.packet(rows=rows))))

    def test_not_applicable_without_reason_is_reported(self):
        rows = [self.row('AC-1'), self.row('AC-2', status='NOT_APPLICABLE', actual='n/a', sha='(none)')]
        errors = self.errors(self.packet(rows=rows))
        self.assertTrue(any('NOT_APPLICABLE without a reason' in e for e in errors), errors)

    # --- evidence binding to the head SHA -----------------------------------
    def test_empty_actual_is_reported(self):
        rows = [self.row('AC-1', actual=''), self.row('AC-2')]
        self.assertTrue(any('empty actual' in e for e in self.errors(self.packet(rows=rows))))

    def test_empty_commit_sha_is_reported(self):
        rows = [self.row('AC-1', sha=''), self.row('AC-2')]
        self.assertTrue(any('empty commit_sha' in e for e in self.errors(self.packet(rows=rows))))

    def test_sha_mismatch_is_reported(self):
        rows = [self.row('AC-1', sha='b' * 40), self.row('AC-2')]
        errors = self.errors(self.packet(rows=rows))
        self.assertTrue(any('does not match the declared evidence head SHA' in e for e in errors), errors)

    def test_abbreviated_head_sha_is_reported(self):
        errors = self.errors(self.packet(head='abc1234'))
        self.assertTrue(any('must be a full 40-hex' in e for e in errors), errors)

    # --- repository integration --------------------------------------------
    def test_template_samples_are_valid(self):
        text = (ROOT / validate.TASK_PACKET_DOC).read_text(encoding='utf-8')
        samples = validate.extract_packet_samples(text)
        self.assertGreaterEqual(len(samples), 2)
        for sample in samples:
            with self.subTest(sample=sample['name']):
                self.assertEqual(self.errors(sample['text']), [])

    def test_both_edition_templates_carry_every_field(self):
        for rel in (validate.TASK_PACKET_DOC, validate.ISSUE_TEMPLATE_DOC):
            text = (ROOT / rel).read_text(encoding='utf-8')
            for name in self.evidence_fields + self.structured:
                self.assertIn(f'`{name}`', text, f'{rel} is missing `{name}`')

    def test_kit_validation_passes_on_this_repository(self):
        errors, sample_count = validate.validate_kit(ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(sample_count, 2)

    def test_cli_task_packet_accepts_legal_and_rejects_broken_packet(self):
        legal = self.packet()
        broken = self.packet(rows=[self.row('AC-1', sha='c' * 40), self.row('AC-2')])
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / 'ok.md'
            bad = Path(tmp) / 'bad.md'
            ok.write_text(legal, encoding='utf-8')
            bad.write_text(broken, encoding='utf-8')
            good = subprocess.run([sys.executable, str(SCRIPT), '--task-packet', str(ok)],
                                  capture_output=True, text=True)
            fail = subprocess.run([sys.executable, str(SCRIPT), '--task-packet', str(bad)],
                                  capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn('Task packet validation passed', good.stdout)
        self.assertEqual(fail.returncode, 1, fail.stdout + fail.stderr)
        self.assertIn('does not match the declared evidence head SHA', fail.stdout)


class ResourceDeclarationTests(unittest.TestCase):
    """The optional `declared_resources` field: shape only, empty is never a failure."""

    def setUp(self):
        self.evidence_fields, self.status_values = canonical()
        self.structured = validate.canonical_packet_fields(
            (ROOT / validate.CORE_DOC).read_text(encoding='utf-8'))
        # Reuse the canonical packet builder instead of duplicating the layout.
        self.builder = TaskPacketMatrixTests('test_legal_packet_passes')
        self.builder.evidence_fields = self.evidence_fields
        self.builder.structured = self.structured

    def errors(self, text):
        return validate.validate_task_packet(text, self.evidence_fields, self.status_values,
                                             label='packet', structured_fields=self.structured)

    def test_absent_and_empty_declarations_are_both_legal(self):
        self.assertEqual(self.errors(self.builder.packet()), [])                 # field absent
        self.assertEqual(self.errors(self.builder.packet(resources='')), [])     # field present, empty
        self.assertEqual(self.errors(self.builder.packet(resources='   ')), [])

    def test_well_formed_declaration_passes(self):
        value = 'db:test/mysql-main:exclusive,svc:build/win-01:shared:600,vol:data.1/0:shared'
        self.assertEqual(self.errors(self.builder.packet(resources=f'`{value}`')), [])

    def test_malformed_entries_are_reported(self):
        cases = {
            'db:test/main': 'mode shared or exclusive',
            'db:test/main:write': 'mode shared or exclusive',
            'DB:test/main:shared': 'mode shared or exclusive',
            'db:test/main:exclusive:0': 'mode shared or exclusive',
            'db:test main:shared': 'mode shared or exclusive',
            'db:test/*:shared': 'mode shared or exclusive',
            'db:test/../main:shared': 'empty or dots-only path segment',
            'db:test//main:shared': 'empty or dots-only path segment',
        }
        for value, needle in cases.items():
            with self.subTest(value=value):
                errors = self.errors(self.builder.packet(resources=value))
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_trailing_comma_and_duplicates_are_reported(self):
        errors = self.errors(self.builder.packet(resources='db:a:shared,'))
        self.assertTrue(any('empty entry' in e for e in errors), errors)
        errors = self.errors(self.builder.packet(resources='db:a:shared,db:a:exclusive'))
        self.assertTrue(any('declares db:a more than once' in e for e in errors), errors)

    def test_templates_document_the_optional_fields(self):
        packet = (ROOT / validate.TASK_PACKET_DOC).read_text(encoding='utf-8')
        issue = (ROOT / validate.ISSUE_TEMPLATE_DOC).read_text(encoding='utf-8')
        self.assertIn(f'`{validate.RESOURCE_FIELD}`', packet)
        self.assertIn(f'`{validate.LOCKED_RESOURCE_FIELD}`', issue)
        self.assertIn('optional', packet.lower())
        # A filled-in sample must stay readable by the same validator.
        filled = self.builder.packet(resources='db:test/main:exclusive')
        self.assertEqual(validate.resource_declaration_errors(filled, 'packet'), [])

    def test_cli_rejects_a_broken_resource_declaration(self):
        broken = self.builder.packet(resources='db:Test main:write')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.md'
            path.write_text(broken, encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), '--task-packet', str(path)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('declared_resources', result.stdout)


class PlanLayerSplitTests(unittest.TestCase):
    """PLAN.md carries the design goals; phases and task blocks live in a docs plan."""

    def test_implementation_plan_template_is_in_the_release_manifest(self):
        self.assertIn('templates/IMPLEMENTATION-PLAN.md', validate.REQUIRED)
        self.assertTrue((ROOT / 'templates' / 'IMPLEMENTATION-PLAN.md').is_file())

    def test_design_template_points_to_the_separate_phase_plan(self):
        text = (ROOT / 'templates' / 'PLAN.md').read_text(encoding='utf-8')
        self.assertIn('templates/IMPLEMENTATION-PLAN.md', text)
        for needle in ('Allowed paths', 'Depends on', 'AC-1'):
            self.assertNotIn(needle, text,
                             f'templates/PLAN.md must not carry the task block field {needle!r}')

    def test_phase_plan_template_carries_phases_and_task_blocks(self):
        text = (ROOT / 'templates' / 'IMPLEMENTATION-PLAN.md').read_text(encoding='utf-8')
        for needle in ('Phase', 'Goal', 'Allowed paths', 'Depends on', 'AC-1',
                       '当前状态', '维护规则'):
            self.assertIn(needle, text)

    def test_documented_required_file_count_matches_the_manifest(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        numbers = set(re.findall(r'(\d+)\s*项必需文件', readme))
        numbers |= set(re.findall(r'(\d+)\s*required files', readme))
        self.assertEqual(numbers, {str(len(validate.REQUIRED))})


if __name__ == '__main__':
    unittest.main()
