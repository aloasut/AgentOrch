"""Scope resolution tests (#120, design §8.2).

Every case is simulated: environment mappings and TTY names are supplied
explicitly, so no test needs a real terminal, a personal machine fact or a
network connection. Filesystem cases use a throwaway temporary project root.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_selection import scope  # noqa: E402

SCOPE_ENV = scope.NAMESPACE_ENV


class ScopeResolutionTests(unittest.TestCase):
    def resolve(self, env=None, **kwargs):
        payload = {} if env is None else dict(env)
        return scope.resolve_scope(env=payload, **kwargs)

    # --- priority and stability --------------------------------------------
    def test_runtime_session_and_tty_are_folded_into_one_scope(self):
        resolution = self.resolve(
            {SCOPE_ENV: 'work', 'AGENTORCH_RUNTIME_SESSION_ID': 'session-1'},
            tty_name='/dev/pts/1')
        self.assertTrue(resolution.has_scope)
        self.assertTrue(resolution.has_identity)
        self.assertTrue(resolution.scope_id.startswith('work--'))
        self.assertIn('runtime-session:AGENTORCH_RUNTIME_SESSION_ID',
                      resolution.identity_sources)
        self.assertIn('tty', resolution.identity_sources)
        self.assertTrue(resolution.history_allowed)
        self.assertIsNone(resolution.error)

    def test_same_identity_is_stable_across_calls(self):
        env = {SCOPE_ENV: 'work', 'AGENTORCH_RUNTIME_SESSION_ID': 'session-1'}
        first = self.resolve(env, tty_name='/dev/pts/1')
        second = self.resolve(env, tty_name='/dev/pts/1')
        self.assertEqual(first.scope_id, second.scope_id)
        self.assertEqual(first.identity_fingerprint, second.identity_fingerprint)

    def test_same_tty_but_different_runtime_session_differs(self):
        env = {SCOPE_ENV: 'work'}
        first = self.resolve(dict(env, AGENTORCH_RUNTIME_SESSION_ID='a'),
                             tty_name='/dev/pts/1')
        second = self.resolve(dict(env, AGENTORCH_RUNTIME_SESSION_ID='b'),
                              tty_name='/dev/pts/1')
        self.assertNotEqual(first.scope_id, second.scope_id)

    def test_same_explicit_id_different_tty_produces_different_scopes(self):
        env = {SCOPE_ENV: 'shared-name'}
        first = self.resolve(env, tty_name='/dev/pts/1')
        second = self.resolve(env, tty_name='/dev/pts/2')
        self.assertNotEqual(first.scope_id, second.scope_id)
        self.assertTrue(first.scope_id.startswith('shared-name--'))
        self.assertTrue(second.scope_id.startswith('shared-name--'))

    def test_same_explicit_id_different_session_produces_different_scopes(self):
        env = {SCOPE_ENV: 'shared-name'}
        first = self.resolve(dict(env, AGENTORCH_RUNTIME_SESSION_ID='one'))
        second = self.resolve(dict(env, AGENTORCH_RUNTIME_SESSION_ID='two'))
        self.assertNotEqual(first.scope_id, second.scope_id)

    def test_longest_explicit_namespace_with_identity_stays_within_limit(self):
        namespace = 'x' * scope.MAX_SCOPE_ID_LENGTH
        resolution = self.resolve({SCOPE_ENV: namespace}, tty_name='/dev/pts/1')
        self.assertTrue(resolution.has_scope)
        self.assertLessEqual(len(resolution.scope_id), scope.MAX_SCOPE_ID_LENGTH)
        self.assertLessEqual(len(resolution.scope_id.encode('utf-8')),
                             scope.MAX_SCOPE_ID_BYTES)
        self.assertEqual(scope.validate_scope_id(resolution.scope_id),
                         resolution.scope_id)
        other_terminal = self.resolve({SCOPE_ENV: namespace}, tty_name='/dev/pts/2')
        self.assertNotEqual(resolution.scope_id, other_terminal.scope_id)
        with tempfile.TemporaryDirectory() as tmp:
            path = scope.scope_directory(tmp, resolution.scope_id)
            expected_parent = (Path(tmp).resolve() / '.local' / 'agent-orch').resolve()
            self.assertEqual(path.resolve().parent, expected_parent)

    def test_long_namespaces_sharing_a_prefix_do_not_collide(self):
        first = self.resolve(
            {SCOPE_ENV: 'a' * (scope.MAX_SCOPE_ID_LENGTH - 1) + 'b'},
            tty_name='/dev/pts/1')
        second = self.resolve(
            {SCOPE_ENV: 'a' * (scope.MAX_SCOPE_ID_LENGTH - 1) + 'c'},
            tty_name='/dev/pts/1')
        self.assertNotEqual(first.scope_id, second.scope_id)
        # Both keep the same readable prefix; the full namespace digest is what
        # prevents a truncation collision.
        self.assertGreaterEqual(len(os.path.commonprefix(
            [first.scope_id, second.scope_id])), 40)

    def test_runtime_session_alone_is_enough(self):
        resolution = self.resolve(
            {'AGENTORCH_RUNTIME_SESSION_ID': 'session-9'}, tty_name=None)
        self.assertTrue(resolution.has_scope)
        self.assertEqual(resolution.mode, 'identity')
        self.assertTrue(resolution.scope_id.startswith('session-'))

    def test_explicit_namespace_alone_is_a_readable_scope(self):
        resolution = self.resolve({SCOPE_ENV: 'my-terminal'}, tty_name=None)
        self.assertEqual(resolution.scope_id, 'my-terminal')
        self.assertEqual(resolution.mode, 'namespace-only')
        self.assertTrue(resolution.history_allowed)
        self.assertIn('unique', resolution.warning)

    # --- explicit namespace reuse ------------------------------------------
    def test_reusing_an_explicit_namespace_without_identity_disables_history(self):
        resolution = self.resolve(
            {SCOPE_ENV: 'my-terminal'}, tty_name=None,
            namespace_claims=('a' * 64,))
        self.assertEqual(resolution.scope_id, 'my-terminal')
        self.assertFalse(resolution.history_allowed)
        self.assertIn('isolation cannot be proven', resolution.warning)

    def test_reusing_an_explicit_namespace_with_a_new_identity_is_allowed(self):
        resolution = self.resolve(
            {SCOPE_ENV: 'my-terminal', 'AGENTORCH_RUNTIME_SESSION_ID': 'new'},
            tty_name=None, namespace_claims=('b' * 64,))
        self.assertTrue(resolution.history_allowed)
        self.assertIn('shared', resolution.warning)

    def test_unverified_claim_keeps_history_for_a_verified_identity(self):
        resolution = self.resolve(
            {SCOPE_ENV: 'my-terminal', 'AGENTORCH_RUNTIME_SESSION_ID': 'new'},
            tty_name=None, namespace_claims=('unverified',))
        self.assertTrue(resolution.history_allowed)
        self.assertIn('without a verifiable terminal identity', resolution.warning)

    # --- fail closed --------------------------------------------------------
    def test_no_identity_and_no_namespace_fails_closed(self):
        resolution = self.resolve({}, tty_name=None)
        self.assertIsNone(resolution.scope_id)
        self.assertFalse(resolution.has_scope)
        self.assertFalse(resolution.history_allowed)
        self.assertIn(SCOPE_ENV, resolution.error)
        self.assertIn('shared / default', resolution.error)
        with self.assertRaises(scope.ScopeIdentityError):
            resolution.require_scope()

    def test_fail_closed_result_has_no_scope_id(self):
        resolution = self.resolve({}, tty_name=None)
        self.assertIsNone(resolution.as_dict()['scope_id'])
        self.assertFalse(resolution.as_dict()['history_allowed'])

    # --- TTY probing is replaceable ----------------------------------------
    def test_tty_probe_is_used_when_no_name_is_supplied(self):
        with mock.patch.object(scope, 'probe_tty_name', return_value='/dev/pts/9'):
            resolution = self.resolve({SCOPE_ENV: 'work'})
        self.assertIn('tty', resolution.identity_sources)
        self.assertTrue(resolution.has_scope)

    def test_tty_probe_returning_none_means_no_identity(self):
        with mock.patch.object(scope, 'probe_tty_name', return_value=None):
            resolution = self.resolve({SCOPE_ENV: 'work'})
        self.assertEqual(resolution.identity_sources, ())
        self.assertEqual(resolution.mode, 'namespace-only')

    # --- no raw terminal path is stored ------------------------------------
    def test_resolution_never_exposes_the_raw_terminal_path(self):
        resolution = self.resolve({SCOPE_ENV: 'work'}, tty_name='/dev/pts/7')
        payload = json.dumps(resolution.as_dict())
        self.assertNotIn('/dev/pts/7', payload)
        self.assertNotIn('/dev/pts/7', resolution.scope_id)
        self.assertNotIn('/dev/pts/7', resolution.identity_fingerprint)

    # --- explicit source list ----------------------------------------------
    def test_identity_environment_sources_are_explicit_and_auditable(self):
        names = [name for name, _description in scope.IDENTITY_ENV_VARS]
        self.assertIn('AGENTORCH_RUNTIME_SESSION_ID', names)
        self.assertIn('TERM_SESSION_ID', names)
        self.assertIn('WT_SESSION', names)
        self.assertNotIn(SCOPE_ENV, names)
        for name, description in scope.IDENTITY_ENV_VARS:
            with self.subTest(name=name):
                self.assertTrue(name.isupper())
                self.assertTrue(description)
        self.assertEqual(len(names), len(set(names)))


class ScopeIdSafetyTests(unittest.TestCase):
    INVALID = (
        '',
        '.',
        '..',
        '../escape',
        'a/b',
        'a\\b',
        '/absolute',
        '\\absolute',
        'C:' + '\\' + 'Users' + '\\name',
        'C:' + '/' + 'Users' + '/name',
        'a..b',
        'a b',
        ' leading',
        'trailing ',
        'tab\there',
        'line\nbreak',
        'nul\x00byte',
        'zero\u200bwidth',
        '.hidden',
        '_hidden',
        'trailing.',
        'x' * (scope.MAX_SCOPE_ID_LENGTH + 1),
        'CON',
        'con.txt',
    )

    def test_unsafe_ids_are_rejected(self):
        for value in self.INVALID:
            with self.subTest(value=repr(value)):
                with self.assertRaises(scope.UnsafeScopeId):
                    scope.validate_scope_id(value)

    def test_safe_ids_are_accepted(self):
        for value in ('term-a', 'work_1', 'team.alpha', '终端-1'):
            with self.subTest(value=value):
                self.assertEqual(scope.validate_scope_id(value), value)

    def test_scope_directory_stays_under_the_project_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = scope.scope_directory(tmp, 'term-a')
            expected_parent = (Path(tmp).resolve() / '.local' / 'agent-orch').resolve()
        self.assertEqual(path.resolve().parent, expected_parent)

    def test_scope_directory_rejects_traversal_and_absolute_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ('../outside', '/tmp/outside', 'a/b'):
                with self.subTest(value=value):
                    with self.assertRaises(scope.UnsafeScopeId):
                        scope.scope_directory(tmp, value)

    def test_symlinked_scope_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp).resolve() / '.local' / 'agent-orch'
            store.mkdir(parents=True)
            original = Path.is_symlink

            def fake(path):
                return path == store / 'linked' or original(path)

            with mock.patch.object(Path, 'is_symlink', fake):
                with self.assertRaises(scope.UnsafeScopeId):
                    scope.scope_directory(tmp, 'linked')

    def test_symlinked_store_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path.is_symlink

            def fake(path):
                return path.name == 'agent-orch' or original(path)

            with mock.patch.object(Path, 'is_symlink', fake):
                with self.assertRaises(scope.UnsafeScopeId):
                    scope.store_root(tmp)


if __name__ == '__main__':
    unittest.main()
