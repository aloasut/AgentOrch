"""Local agent-selection records: per-terminal scope + Markdown-only store (#120).

Phase D S1 of ``docs/design/agent-role-discovery-and-model-selection.md`` §8.
Two modules, one direction of dependency:

``scope``        resolves a stable, per-terminal scope id from a runtime session
                 id, an interactive TTY identity and the explicit
                 ``AGENTORCH_SCOPE_ID`` namespace. Raw terminal paths are hashed
                 and never stored; when no stable identity exists the resolver
                 fails closed instead of falling back to a shared directory.
``local_store``  persists records as Markdown under
                 ``.local/agent-orch/<scope-id>/`` with atomic writes, an explicit
                 concurrency conflict and a privacy scan.

The store is intentionally *not* a capability model: C1-C4 / C1-C8 stay defined
in ``kit/orchestration.md`` and ``templates/runtime-capability.md``. This package
records references and short summaries only.

Standard library only; no network, no third-party dependency.
"""

__all__ = ['scope', 'local_store']
