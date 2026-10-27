"""Markdown-only local store tests (#120, design §8.3 / §8.4).

Every test uses a temporary project root. Nothing here reads or writes the real
``.local`` directory, a personal machine fact or a network service.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection import local_store, scope  # noqa: E402

NOW = '2026-10-27T10:00:00Z'
LATER = '2026-10-27T11:00:00Z'


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def store(self, scope_id='term-a', **kwargs):
        return local_store.LocalStore(self.root, scope_id, **kwargs)

    def initialized(self, scope_id='term-a', **kwargs):
        store = self.store(scope_id, **kwargs)
        store.initialize(now=NOW)
        return store

    def doc(self, store, name):
        return store.directory / name

    def try_symlink(self, target, link):
        try:
            os.symlink(target, link)
            return True
        except (OSError, NotImplementedError):
            return False


class LayoutTests(StoreFixture):
    def test_initialize_creates_only_markdown_documents(self):
        store = self.initialized()
        files = sorted(path.name for path in store.directory.iterdir())
        self.assertEqual(files, sorted(local_store.DOCUMENTS))
        for path in store.directory.iterdir():
            with self.subTest(name=path.name):
                self.assertTrue(path.is_file())
                self.assertEqual(path.suffix, '.md')
        self.assertFalse((store.directory / 'state.json').exists())
        self.assertFalse((store.directory / 'state.sqlite3').exists())

    def test_scope_metadata_records_identity_without_a_raw_terminal_path(self):
        store = local_store.LocalStore(
            self.root, 'work--' + 'a' * 16,
            metadata={'namespace': 'work', 'identity_fingerprint': 'a' * 64,
                      'identity_sources': ('tty',)})
        store.initialize(now=NOW)
        meta = store.read_scope_metadata()
        self.assertEqual(meta['scope_id'], 'work--' + 'a' * 16)
        self.assertEqual(meta['namespace'], 'work')
        self.assertEqual(meta['identity_sources'], 'tty')
        self.assertEqual(meta['history_allowed'], 'true')
        readme = self.doc(store, 'README.md').read_text(encoding='utf-8')
        self.assertNotIn('/dev/', readme)

    def test_initialize_is_idempotent_and_preserves_existing_records(self):
        store = self.initialized()
        store.append_record('selection-history.md', summary='first event',
                            source_class='OBSERVED', now=LATER)
        store.initialize(now='2026-10-27T12:00:00Z')
        records = store.read_records('selection-history.md')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].summary, 'first event')

    def test_initialize_refuses_a_corrupt_readme(self):
        store = self.store()
        store.directory.mkdir(parents=True)
        (store.directory / 'README.md').write_text(
            '# no metadata here\n', encoding='utf-8')
        with self.assertRaises(local_store.StoreCorruptError):
            store.initialize(now=NOW)

    def test_initialize_reports_a_file_where_the_scope_directory_belongs(self):
        store = self.store()
        store.directory.parent.mkdir(parents=True)
        store.directory.write_text('not a directory', encoding='utf-8')
        with self.assertRaises(local_store.StoreError):
            store.initialize(now=NOW)


class RecordTests(StoreFixture):
    def test_append_record_carries_scope_time_source_and_status(self):
        store = self.initialized()
        record = store.append_record(
            'selection-history.md', summary='chose candidate A',
            source_class='OBSERVED', status='RECORDED',
            details={'evidence': 'PR #120 comment'}, now=LATER)
        self.assertEqual(record.scope_id, 'term-a')
        self.assertEqual(record.created_at, LATER)
        self.assertEqual(record.updated_at, LATER)
        self.assertEqual(record.source_class, 'OBSERVED')
        self.assertEqual(record.status, 'RECORDED')
        parsed = store.read_records('selection-history.md')
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].summary, 'chose candidate A')
        self.assertEqual(parsed[0].details, {'evidence': 'PR #120 comment'})

    def test_repeated_append_keeps_both_history_events(self):
        store = self.initialized()
        first = store.append_record('selection-history.md', summary='choose A',
                                    source_class='INFERRED', now=NOW)
        second = store.append_record('selection-history.md', summary='choose A',
                                     source_class='INFERRED', now=LATER)
        self.assertNotEqual(first.record_id, second.record_id)
        records = store.read_records('selection-history.md')
        self.assertEqual([record.summary for record in records], ['choose A', 'choose A'])
        self.assertEqual({record.source_class for record in records}, {'INFERRED'})

    def test_inferred_is_not_rewritten_as_observed(self):
        store = self.initialized()
        store.append_record('runtime-capabilities.md', summary='provisional',
                            source_class='INFERRED', now=NOW)
        record = store.read_records('runtime-capabilities.md')[0]
        self.assertEqual(record.source_class, 'INFERRED')

    def test_unknown_source_class_or_status_is_rejected(self):
        store = self.initialized()
        with self.assertRaises(ValueError):
            store.append_record('selection-history.md', summary='x',
                                source_class='PASS', now=NOW)
        with self.assertRaises(ValueError):
            store.append_record('selection-history.md', summary='x',
                                status='PASS', now=NOW)
        self.assertEqual(store.read_records('selection-history.md'), ())

    def test_append_on_an_uninitialized_scope_is_reported(self):
        with self.assertRaises(local_store.StoreNotInitializedError):
            self.store().append_record('selection-history.md', summary='x', now=NOW)

    def test_non_markdown_document_names_are_rejected(self):
        store = self.initialized()
        with self.assertRaises(ValueError):
            store.append_record('state.json', summary='x', now=NOW)
        with self.assertRaises(ValueError):
            store.read_document('state.json')

    def test_empty_document_is_empty_not_pass(self):
        store = self.initialized()
        state = store.read_document('selection-history.md')
        self.assertEqual(state.status, 'EMPTY')
        self.assertFalse(state.passing)
        self.assertTrue(state.ok)

    def test_two_scopes_do_not_read_each_other(self):
        first = self.initialized('term-a')
        second = self.initialized('term-b')
        first.append_record('selection-history.md', summary='only in a',
                            source_class='OBSERVED', now=NOW)
        self.assertEqual(first.read_records('selection-history.md')[0].summary, 'only in a')
        self.assertEqual(second.read_records('selection-history.md'), ())
        self.assertNotEqual(first.directory, second.directory)


class CorruptAndMissingTests(StoreFixture):
    def test_missing_document_is_reported_and_never_pass(self):
        store = self.initialized()
        self.doc(store, 'selection-history.md').unlink()
        state = store.read_document('selection-history.md')
        self.assertEqual(state.status, 'MISSING')
        self.assertFalse(state.exists)
        self.assertFalse(state.passing)
        self.assertTrue(state.issues)
        with self.assertRaises(local_store.MissingRecordError):
            store.read_records('selection-history.md')

    def test_record_without_metadata_is_reported(self):
        store = self.initialized()
        self.doc(store, 'selection-history.md').write_text(
            '# selection-history\n\n### broken\n\n- summary: no metadata\n',
            encoding='utf-8')
        state = store.read_document('selection-history.md')
        self.assertEqual(state.status, 'UNKNOWN')
        self.assertFalse(state.ok)
        self.assertFalse(state.passing)
        self.assertTrue(any('missing metadata block' in issue for issue in state.issues))
        with self.assertRaises(local_store.StoreCorruptError):
            store.read_records('selection-history.md')

    def test_unclosed_metadata_block_is_reported(self):
        store = self.initialized()
        self.doc(store, 'selection-history.md').write_text(
            '# selection-history\n\n### broken\n\n'
            + local_store.RECORD_META_START + '\n'
            + '- scope_id: `term-a`\n', encoding='utf-8')
        state = store.read_document('selection-history.md')
        self.assertEqual(state.status, 'UNKNOWN')
        self.assertTrue(any('not closed' in issue for issue in state.issues))

    def test_record_from_another_scope_is_reported(self):
        store = self.initialized()
        store.append_record('selection-history.md', summary='event',
                            source_class='OBSERVED', now=NOW)
        path = self.doc(store, 'selection-history.md')
        path.write_text(path.read_text(encoding='utf-8').replace(
            '- scope_id: `term-a`', '- scope_id: `term-b`'), encoding='utf-8')
        state = store.read_document('selection-history.md')
        self.assertEqual(state.status, 'UNKNOWN')
        self.assertTrue(any('does not match' in issue for issue in state.issues))

    def test_broken_link_document_is_reported(self):
        store = self.initialized()
        target = store.directory / 'selection-history.md'
        link = store.directory / 'observed-performance.md'
        link.unlink()
        made_link = self.try_symlink(target.name + '.missing', link)
        if made_link:
            state = store.read_document('observed-performance.md')
        else:
            original = Path.is_symlink
            with mock.patch.object(
                    Path, 'is_symlink',
                    lambda path: path == link or original(path)):
                state = store.read_document('observed-performance.md')
        self.assertEqual(state.status, 'CORRUPT')
        self.assertFalse(state.exists)
        self.assertTrue(any('broken link' in issue for issue in state.issues))
        self.assertFalse(state.passing)

    def test_scope_metadata_missing_a_required_field_is_reported(self):
        store = self.initialized()
        path = self.doc(store, 'README.md')
        text = path.read_text(encoding='utf-8').replace(
            '- scope_id: `term-a`\n', '')
        path.write_text(text, encoding='utf-8')
        with self.assertRaises(local_store.StoreCorruptError):
            store.read_scope_metadata()


class WriteFailureTests(StoreFixture):
    def test_write_failure_is_reported_and_does_not_add_a_record(self):
        store = self.initialized()
        before = self.doc(store, 'selection-history.md').read_text(encoding='utf-8')
        with mock.patch.object(local_store.os, 'replace',
                               side_effect=PermissionError('read-only directory')):
            with self.assertRaises(local_store.StoreWriteError):
                store.append_record('selection-history.md', summary='lost write',
                                    source_class='OBSERVED', now=NOW)
        after = self.doc(store, 'selection-history.md').read_text(encoding='utf-8')
        self.assertEqual(before, after)
        self.assertEqual(store.read_records('selection-history.md'), ())

    def test_existing_writer_lock_is_a_conflict_not_a_silent_overwrite(self):
        store = self.initialized()
        lock = store.directory / local_store.LOCK_NAME
        lock.write_text('pid=other\n', encoding='utf-8')
        with self.assertRaises(local_store.StoreConflictError):
            store.append_record('selection-history.md', summary='blocked',
                                source_class='OBSERVED', now=NOW)
        lock.unlink()
        store.append_record('selection-history.md', summary='after retry',
                            source_class='OBSERVED', now=LATER)
        self.assertEqual(len(store.read_records('selection-history.md')), 1)

    def test_concurrent_appends_are_serialized_or_explicitly_conflicted(self):
        store = self.initialized()
        barrier = threading.Barrier(2)
        results = []

        def worker(index):
            try:
                barrier.wait(timeout=10)
                store.append_record('selection-history.md',
                                    summary=f'concurrent event {index}',
                                    source_class='OBSERVED', now=LATER)
                results.append('written')
            except local_store.StoreConflictError:
                results.append('conflict')

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(len(results), 2)
        records = store.read_records('selection-history.md')
        self.assertEqual(len(records), results.count('written'))
        self.assertFalse(store.read_document('selection-history.md').issues)

    def test_read_only_directory_reports_a_write_error(self):
        store = self.initialized()
        original_mode = store.directory.stat().st_mode
        os.chmod(store.directory, 0o500)
        try:
            try:
                store.append_record('selection-history.md', summary='read only',
                                    source_class='OBSERVED', now=LATER)
            except local_store.StoreWriteError:
                failed = True
            else:
                failed = False
            if not failed:
                # An elevated user (or a platform that ignores directory modes)
                # can still write; inject the same permission failure instead of
                # letting the scenario silently pass.
                with mock.patch.object(local_store.os, 'replace',
                                       side_effect=PermissionError('read-only')):
                    with self.assertRaises(local_store.StoreWriteError):
                        store.append_record('selection-history.md', summary='read only',
                                            source_class='OBSERVED', now=LATER)
        finally:
            os.chmod(store.directory, original_mode)

    def test_no_identity_and_no_namespace_creates_no_shared_directory(self):
        with self.assertRaises(scope.ScopeIdentityError):
            local_store.open_store(self.root, env={}, tty_name=None)
        self.assertFalse((self.root / '.local').exists())

    def test_history_disabled_refuses_read_and_write(self):
        store = self.store(history_allowed=False)
        with self.assertRaises(local_store.HistoryDisabledError):
            store.initialize(now=NOW)
        store.directory.mkdir(parents=True)
        with self.assertRaises(local_store.HistoryDisabledError):
            store.read_document('selection-history.md')
        with self.assertRaises(local_store.HistoryDisabledError):
            store.append_record('selection-history.md', summary='x', now=NOW)


class PrivacyTests(StoreFixture):
    SECRETS = (
        'sk-' + 'A1b2C3d4E5f6G7h8I9j0K1l2',
        'gh' + 'p_' + 'A' * 30,
        'github' + '_pat_' + 'A' * 30,
        '-' * 5 + 'BEGIN RSA PRIVATE KEY' + '-' * 5,
        'AK' + 'IA' + '1234567890ABCDEF',
        'Bearer ' + 'A' * 30,
        '/dev/pts/7',
        '/home/' + 'someone/notes.md',
        'C:' + '\\' + 'Users' + '\\name',
    )

    def test_secret_shapes_and_terminal_paths_are_refused(self):
        store = self.initialized()
        for secret in self.SECRETS:
            with self.subTest(secret=secret[:12]):
                with self.assertRaises(local_store.StorePrivacyError):
                    store.append_record('selection-history.md', summary=secret,
                                        source_class='OBSERVED', now=NOW)
        self.assertEqual(store.read_records('selection-history.md'), ())

    def test_secret_in_a_detail_is_refused(self):
        store = self.initialized()
        with self.assertRaises(local_store.StorePrivacyError):
            store.append_record('selection-history.md', summary='looks harmless',
                                source_class='OBSERVED',
                                details={'evidence': self.SECRETS[0]}, now=NOW)

    def test_multi_line_and_long_text_are_refused(self):
        store = self.initialized()
        with self.assertRaises(ValueError):
            store.append_record('selection-history.md', summary='line one\nline two',
                                source_class='OBSERVED', now=NOW)
        with self.assertRaises(ValueError):
            store.append_record('selection-history.md', summary='x' * 5000,
                                source_class='OBSERVED', now=NOW)
        with self.assertRaises(ValueError):
            store.append_record('selection-history.md', summary='x',
                                source_class='OBSERVED',
                                details={'evidence': '<!-- injected -->'}, now=NOW)


class IndexAndClaimTests(StoreFixture):
    def test_index_refresh_is_idempotent_and_counts_records(self):
        store = self.initialized()
        store.append_record('selection-history.md', summary='one',
                            source_class='OBSERVED', now=NOW)
        store.append_record('selection-history.md', summary='two',
                            source_class='OBSERVED', now=LATER)
        store.refresh_index(now='2026-10-27T12:00:00Z')
        first = self.doc(store, 'README.md').read_text(encoding='utf-8')
        store.refresh_index(now='2026-10-27T13:00:00Z')
        second = self.doc(store, 'README.md').read_text(encoding='utf-8')
        self.assertEqual(first, second)
        self.assertIn('| [selection-history.md](selection-history.md) | 2 | ' + LATER + ' |',
                      first)
        self.assertIn('| [agent-registry.md](agent-registry.md) | 0 | (none) |', first)

    def test_index_reports_a_missing_document_as_unknown_not_pass(self):
        store = self.initialized()
        self.doc(store, 'selection-history.md').unlink()
        store.refresh_index(now=LATER)
        readme = self.doc(store, 'README.md').read_text(encoding='utf-8')
        self.assertIn('| [selection-history.md](selection-history.md) | UNKNOWN | UNKNOWN |',
                      readme)
        self.assertNotIn('PASS', readme)

    def test_namespace_claims_are_markdown_and_detect_reuse(self):
        key = 'a' * 64
        store = local_store.LocalStore(
            self.root, 'ns1--' + 'a' * 16,
            metadata={'namespace': 'ns1', 'identity_fingerprint': key,
                      'identity_sources': ('tty',)})
        store.initialize(now=NOW)
        claims = local_store.read_namespace_claims(self.root, 'ns1')
        self.assertEqual(claims, (key,))
        claims_file = self.root / '.local' / 'agent-orch' / local_store.CLAIMS_DIRNAME / 'ns1.md'
        self.assertEqual(claims_file.suffix, '.md')
        resolution = scope.resolve_scope(
            env={scope.NAMESPACE_ENV: 'ns1'}, tty_name=None,
            namespace_claims=claims)
        self.assertFalse(resolution.history_allowed)
        self.assertIn('isolation cannot be proven', resolution.warning)

    def test_open_store_records_a_claim_and_disables_unverifiable_reuse(self):
        first = local_store.open_store(
            self.root, env={scope.NAMESPACE_ENV: 'ns1'}, tty_name='/dev/pts/1')
        first.initialize(now=NOW)
        self.assertTrue(local_store.read_namespace_claims(self.root, 'ns1'))
        second = local_store.open_store(
            self.root, env={scope.NAMESPACE_ENV: 'ns1'}, tty_name=None)
        self.assertFalse(second.history_allowed)
        with self.assertRaises(local_store.HistoryDisabledError):
            second.read_document('selection-history.md')


if __name__ == '__main__':
    unittest.main()
