"""Dependency and scope guard for the update engine (AC-6).

The engine must stay pure standard library and must never touch the existing
scheduler / task state machine.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'scripts' / 'update_agentorch'


class DependencyTests(unittest.TestCase):
    def test_package_exists_and_has_sources(self):
        self.assertTrue(PACKAGE.is_dir())
        self.assertTrue(list(PACKAGE.glob('*.py')))

    def test_only_standard_library_and_own_package_are_imported(self):
        allowed = set(sys.stdlib_module_names) | {'update_agentorch'}
        violations = []
        for path in sorted(PACKAGE.glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name.split('.')[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        continue  # relative import inside the package
                    if node.module:
                        modules = [node.module.split('.')[0]]
                for module in modules:
                    if module not in allowed:
                        violations.append(f'{path.name}:{node.lineno}: {module}')
        self.assertEqual(violations, [])

    def test_engine_does_not_import_the_task_state_machine(self):
        for path in sorted(PACKAGE.glob('*.py')):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('orchestrator.py', text, path.name)

    def test_no_third_party_requirement_files_are_added(self):
        for name in ('requirements.txt', 'pyproject.toml', 'setup.py', 'Pipfile'):
            self.assertFalse((PACKAGE / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
