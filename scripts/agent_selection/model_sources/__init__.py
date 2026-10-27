"""Vendor-neutral model-evaluation sources for role-specific selection (#122, S3).

Design contract: ``docs/design/agent-role-discovery-and-model-selection.md``
§6–§7. The package has two jobs and no third one:

``snapshot``             defines the provider-independent ``ModelSnapshot`` /
                         ``ModelEvaluation`` objects, the fetch statuses and the
                         freshness rules. Missing data is ``UNKNOWN``; a value
                         is never filled in to make a report look complete.
``artificial_analysis``  is one optional adapter for the official Artificial
                         Analysis Data API. It reads its key from a protected
                         environment variable, never stores the key, and never
                         reaches the network at import time. No other vendor is
                         built in, and no third-party package is used.

This package does not decide which model a role should use; that lives in
``scripts.agent_selection.model_selection`` and reuses the S2 hard filters.
The base governance CLI never imports this package, so an offline machine and a
missing API key degrade to ``UNKNOWN`` / ``STALE`` instead of a failure.

Standard library only.
"""

__all__ = ['snapshot', 'artificial_analysis']
