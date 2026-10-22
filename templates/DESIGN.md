# Design Document

> Filled in by the Execution Agent and reviewed section by section during chunked sign-off. Keep it to one page.

## Problem
<!-- One or two sentences: what problem are we solving and who/what does it affect? -->
- Problem to solve:
- Impact / affected users or flows:

## Proposed solution
<!-- Describe the approach in terms of user-visible outcomes, not internals. -->
- Summary of the approach:
- What the user will be able to do afterwards:

## Alternatives considered
<!-- List realistic options rejected and why. "Do nothing" counts. -->
- Option considered:
- Why rejected:

## Shared resource locks
<!-- Only when this design depends on resources that are not identified by file paths
     (test database, shared build environment, serial test slot, fixture volume).
     The semantics are frozen in ../docs/design/RESOURCE-LOCKS.md — reference it, do not restate it. -->
- Named resources this design needs (`<resource_id>` + mode `shared` / `exclusive`):
- Why a path lock alone is not enough:
- What happens on lock conflict, lease expiry and holder crash:
- Backend limits acknowledged (`local` atomic within one database file; `github` is an advisory registration, never an atomic lock):

## Risks and trade-offs
<!-- What could go wrong, and what are we consciously giving up? -->
- Risks and mitigations:
- Accepted trade-offs:

## Open decisions
<!-- Anything requiring the owner's call before implementation proceeds. -->
- Question / options / recommendation:
