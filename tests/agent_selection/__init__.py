"""Allow ``python3 -m unittest tests.agent_selection`` to run the package.

``unittest`` does not discover submodules when given a package name, so this
package registers its own modules explicitly. ``discover -s tests`` picks the
same modules up through the ``test_*.py`` naming.
"""
import importlib

_TEST_MODULES = ('test_scope', 'test_local_store')


def load_tests(loader, standard_tests, pattern):
    for name in _TEST_MODULES:
        module = importlib.import_module(f'{__name__}.{name}')
        standard_tests.addTests(loader.loadTestsFromModule(module))
    return standard_tests
