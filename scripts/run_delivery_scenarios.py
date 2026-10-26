#!/usr/bin/env python3
"""Synthetic delivery regression scenarios for the Agent-Orchestration kit.

This runner answers one question the documents cannot answer by themselves:
does the kit *stop* the failures it describes? Four groups are covered, each
taken from a typical failure mode rather than from a product's private data:

  A  governance / authorization   (evidence gates, revocation, duplicate writes)
  B  migration / versioning       (rerun, partial write, version isolation)
  C  cross-module closeout        (unwired rule, ownership, event barrier, crash,
                                   shared state, locking, rollback and staged failure)
  D  orchestration base           (edition, resource lock, stale SHA, retries, audit)

Every scenario declares its precondition, the defect it injects, the gate that
must fire and the evidence it leaves behind; `docs/testing/delivery-regression-scenarios.md`
carries the same table for humans. Scenarios are synthetic and self-contained:
fixtures are generated in a throw-away directory, nothing is read from or
written to the repository, and no network, credential or external model is used.

Two properties are deliberate:

  * one scenario cannot end the run. A scenario that raises anything (including
    a non-assertion exception such as TypeError) is recorded as ERROR with its
    traceback and the remaining scenarios still execute;
  * a negative group always comes with a positive control, so "everything fails"
    is never mistaken for "the gates work".

Exit codes: 0 all scenarios passed, 1 at least one scenario failed or errored,
2 the runner itself could not run (missing module, unknown --only id, unwritable
--output). Only the standard library is used.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import platform
import shutil
import sys
import tempfile
import traceback
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
SCENARIO_DOC = 'docs/testing/delivery-regression-scenarios.md'
REPORT_SCHEMA = 'agentorch.delivery-scenarios/1'

HEAD_SHA = 'a' * 40
STALE_SHA = 'c' * 40
MERGE_SHA = 'b' * 40

EXIT_PASS = 0
EXIT_SCENARIO_FAILURES = 1
EXIT_TOOL_ERROR = 2

GROUPS = {
    'A': 'governance / authorization',
    'B': 'migration / versioning',
    'C': 'cross-module closeout / shared state, recovery and architecture alignment',
    'D': 'orchestration base / evidence decay',
}


class ToolError(RuntimeError):
    """The runner cannot start; this is not a scenario result."""


class ScenarioFailed(AssertionError):
    """The gate the scenario expected did not fire (or fired for the wrong reason)."""


# --------------------------------------------------------------------------- #
# Synthetic fixtures
# --------------------------------------------------------------------------- #
@dataclass
class Context:
    """Everything a scenario may touch: the two kit modules and a private sandbox."""

    vk: object
    orch: object
    sandbox: Path


@dataclass(frozen=True)
class Scenario:
    id: str
    group: str
    kind: str            # 'positive' control or 'negative' injected defect
    title: str
    precondition: str
    defect: str
    gate: str
    evidence: str
    cleanup: str
    fn: object           # Callable[[Context], list[str]]


@dataclass
class Result:
    scenario: Scenario
    status: str          # PASS / FAIL / ERROR
    evidence: list = field(default_factory=list)
    error: dict = field(default_factory=dict)


def _load_module(name, path):
    if not path.is_file():
        raise ToolError(f'{name}: module not found at {path}')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - surfaced as a tool error, not a scenario
        raise ToolError(f'{name}: cannot import {path}: {exc}') from exc
    return module


@contextlib.contextmanager
def _quiet():
    """Swallow the CLI chatter of orchestrator/init so the report stays readable."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def _require(condition, message):
    if not condition:
        raise ScenarioFailed(message)


def _expect_clean(errors, label):
    if errors:
        raise ScenarioFailed(f'{label}: expected no finding, got: ' + ' | '.join(errors))


def _expect_finding(errors, needle, label):
    hits = [error for error in errors if needle in error]
    if not hits:
        raise ScenarioFailed(f'{label}: expected a finding containing {needle!r}, '
                             f'got: ' + (' | '.join(errors) if errors else '(no finding at all)'))
    return hits[0]


def _expect_refused(call, needle, label):
    """Call something that must be refused and return the refusal message."""
    try:
        call()
    except ScenarioFailed:
        raise
    except Exception as exc:  # noqa: BLE001 - the refusal type is asserted separately
        message = f'{type(exc).__name__}: {exc}'
        if needle not in message:
            raise ScenarioFailed(f'{label}: refused, but the reason never mentions '
                                 f'{needle!r}: {message}') from None
        return message
    raise ScenarioFailed(f'{label}: the call succeeded, but it must be refused')


# --- task packet fixtures ---------------------------------------------------
def _canonical(ctx):
    core = (ROOT / ctx.vk.CORE_DOC).read_text(encoding='utf-8')
    evidence, statuses = ctx.vk.canonical_evidence_fields(core)
    structured = ctx.vk.canonical_packet_fields(core)
    if not evidence or not statuses:
        raise ScenarioFailed(f'cannot read the evidence-item contract from {ctx.vk.CORE_DOC}')
    return evidence, statuses, structured


def _row(evidence_fields, *, ac, status='PASS', actual='2 checks passed', sha=HEAD_SHA,
         notes='(none)', method='`python -m unittest`', expected='the check passes',
         environment='synthetic fixture, stdlib only, local edition',
         ref='synthetic fixture: scenario evidence log'):
    cells = {
        'ac_id': ac, 'method': method, 'expected': expected, 'actual': actual,
        'status': status, 'environment': environment, 'commit_sha': sha,
        'evidence_ref': ref, 'notes': notes,
    }
    missing = [name for name in evidence_fields if name not in cells]
    _require(not missing, f'fixture builder is missing evidence fields: {missing}')
    return '  | ' + ' | '.join(cells[name] for name in evidence_fields) + ' |'


def _packet(ctx, acs, rows, head=HEAD_SHA):
    """Build a filled task packet; `rows` is a list of evidence-matrix lines."""
    evidence_fields, _, structured_fields = _canonical(ctx)
    lines = [
        '- **Task ID:** SYNTH-9001',
        '- **Title:** Synthetic governance task',
        '- **Goal / user-visible result:** the task is judged only by its own evidence',
        '- **Context:** synthetic fixture; no network, credentials or external model',
        '- **Allowed paths:** `src/example.py`',
        '- **Forbidden paths:** every other path in the repository',
        '- **Dependencies (must be VERIFIED):** none',
        '- **Acceptance criteria:**',
    ]
    for mark, ac_id, text in acs:
        lines.append(f'  - [{mark}] {ac_id}: {text}' if text else f'  - [{mark}] {ac_id}:')
    for name in structured_fields:
        lines.append(f'- **{name}:** N/A: covered by the acceptance criteria above')
    lines += [
        '- **Validation commands:** `python -m unittest`',
        '- **Baseline branch / commit:** `main` @ `1111111`',
        '- **Expected branch / Worktree:** `task/9001-synthetic` / `.worktrees/9001-synthetic`',
        f'- **Evidence head SHA:** {head}',
        '- **Evidence matrix:**',
        '  | ' + ' | '.join(evidence_fields) + ' |',
        '  |' + '---|' * len(evidence_fields),
    ]
    lines += list(rows)
    lines += [
        '- **Risks / human decisions:** none identified',
        '- **Delivery evidence:** command output, exit codes, head SHA',
        '- **Hard boundaries:** no self-approval, no merge, no VERIFIED claim',
    ]
    return '\n'.join(lines) + '\n'


def _packet_errors(ctx, text):
    evidence, statuses, structured = _canonical(ctx)
    return ctx.vk.validate_task_packet(text, evidence, statuses,
                                       label='synthetic packet', structured_fields=structured)


# --- orchestrator fixtures --------------------------------------------------
def _project_root(ctx, edition='local', config=None):
    """A throw-away project root with an explicit edition and an initialized store."""
    root = ctx.sandbox / f'project-{edition}'
    root.mkdir(parents=True, exist_ok=True)
    (root/'docs').mkdir(parents=True, exist_ok=True) or (root / 'docs/PROJECT.md').write_text(
        f'# Synthetic project\n\n- `edition`\uFF1A`{edition}`\n', encoding='utf-8')
    (root / '.orchestration').mkdir(exist_ok=True)
    payload = {'retry_cap': 3, 'local_dir': '.local'}
    payload.update(config or {})
    (root / '.orchestration' / 'config.json').write_text(
        json.dumps(payload, sort_keys=True), encoding='utf-8')
    with _quiet():
        ctx.orch.init(root)
    return root


def _add(ctx, root, task_id, paths, resources=None):
    payload = SimpleNamespace(id=task_id, title=task_id, description='synthetic fixture',
                              paths=list(paths), depends=[], acceptance=['synthetic criterion'],
                              resources=list(resources or []))
    with _quiet():
        ctx.orch.task_add(root, payload)


def _ready(ctx, root, task_id):
    with _quiet():
        ctx.orch.task_ready(root, task_id)


def _dispatch(ctx, root, task_id, holder='synthetic-host:1', resources=None):
    options = SimpleNamespace(holder=holder, resource=list(resources or []),
                              actor='scenario-runner', evidence='synthetic scenario')
    with _quiet():
        ctx.orch.task_dispatch(root, task_id, options)


def _status(ctx, root, task_id, dest, head_sha=None, merge_sha=None,
            note='synthetic status change with evidence'):
    args = SimpleNamespace(id=task_id, status=dest, head_sha=head_sha,
                           merge_sha=merge_sha, note=note)
    with _quiet():
        ctx.orch.task_status(root, args)


def _workspace(ctx, root, task_id, head_sha):
    args = SimpleNamespace(id=task_id, head_sha=head_sha, branch='', worktree='', note='')
    with _quiet():
        ctx.orch.set_workspace(root, args)


def _task_row(ctx, root, task_id, columns='status,head_sha,approved_sha,retries'):
    con = ctx.orch.connect(root)
    try:
        return con.execute(f'SELECT {columns} FROM tasks WHERE id=?', (task_id,)).fetchone()
    finally:
        con.close()


def _count(ctx, root, sql, params=()):
    con = ctx.orch.connect(root)
    try:
        return con.execute(sql, params).fetchone()[0]
    finally:
        con.close()


def _drive_to_master_review(ctx, root, task_id, head_sha=HEAD_SHA):
    _ready(ctx, root, task_id)
    _dispatch(ctx, root, task_id)
    _status(ctx, root, task_id, 'IN_PROGRESS')
    _status(ctx, root, task_id, 'REVIEW_READY', head_sha=head_sha)
    _status(ctx, root, task_id, 'MASTER_REVIEW')


# --- migration fixtures -----------------------------------------------------
TARGET_VERSION = '2024'
LEGACY_VERSION = '2014'
LEGACY_RECORDS = (
    {'id': 'role.guard', 'version': LEGACY_VERSION, 'name': 'guard', 'hp': 12},
    {'id': 'role.scout', 'version': LEGACY_VERSION, 'name': 'scout', 'hp': 8},
    {'id': 'role.healer', 'version': LEGACY_VERSION, 'name': 'healer', 'hp': 10},
)


def _write_records(path, records):
    path.write_text(json.dumps({'records': list(records)}, sort_keys=True),
                    encoding='utf-8')


def _read_records(path):
    return json.loads(path.read_text(encoding='utf-8'))['records']


def _migrate(records, target=TARGET_VERSION):
    """Deterministic and idempotent: re-running on migrated rows changes nothing."""
    return [{'id': row['id'], 'version': target, 'name': row['name'],
             'hp': row.get('hp', 10)} for row in records]


def _digest(records):
    payload = json.dumps(records, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _verify_migration(path, expected_version=TARGET_VERSION,
                      expected_count=len(LEGACY_RECORDS)):
    """Independent check of a migration artifact; empty list means consistent."""
    if not path.is_file():
        return [f'migration artifact missing: {path.name}']
    records = _read_records(path)
    problems = []
    if len(records) != expected_count:
        problems.append(f'partial migration: {len(records)} of {expected_count} records present')
    ids = [row['id'] for row in records]
    if len(set(ids)) != len(ids):
        problems.append('duplicate record ids: the rerun was not idempotent')
    for row in records:
        if row.get('version') != expected_version:
            problems.append(f'version isolation broken: {row["id"]} is '
                            f'{row.get("version")!r}, expected {expected_version!r}')
    marker = path.with_suffix('.complete')
    if not marker.is_file():
        problems.append('completion marker missing: the migration never closed out')
    elif marker.read_text(encoding='utf-8').strip() != _digest(records):
        problems.append('completion marker does not match the artifact: the write was interrupted')
    return problems


# --- cross-module fixtures --------------------------------------------------
def _run_turn(*, wire_rule=True, enforce_ownership=True, barrier=True,
              actor='player-1', owner='player-1'):
    """A three-step turn: ownership -> rule -> commit, with switchable defects."""
    events, version = [], 0

    def emit(kind, **extra):
        events.append({'type': kind, 'version': version, **extra})

    if enforce_ownership and actor != owner:
        emit('action_rejected', actor=actor, reason='ownership')
        return events
    if not barrier:
        version += 1
        emit('state_changed', unit='unit-1')
    if wire_rule:
        emit('action_resolved', actor=actor, unit='unit-1')
    if barrier:
        version += 1
        emit('state_committed', unit='unit-1')
        emit('state_changed', unit='unit-1')
    return events


def _check_turn(events, *, actor, owner):
    """Invariants of the frozen contract, checked independently of the emitter."""
    violations, kinds = [], [event['type'] for event in events]
    if 'action_resolved' not in kinds:
        violations.append('frozen rule not wired: action_resolved never emitted')
    elif actor != owner:
        violations.append(f'ownership gap: actor {actor} resolved a unit owned by {owner}')
    if 'state_changed' in kinds:
        for index, kind in enumerate(kinds):
            if kind == 'state_changed' and 'state_committed' not in kinds[:index + 1]:
                violations.append('event barrier missing: state_changed emitted before the commit barrier')
                break
    versions = [event['version'] for event in events]
    if versions != sorted(versions):
        violations.append('event versions go backwards')
    return violations


# --- shared-state / recovery fixtures --------------------------------------
# These model the shapes a delivery task has to get right when it touches shared
# mutable state: one read-modify-write body with several call sites, a lock that
# lives next to the data but outside the rolled-back subtree, a snapshot-based
# rollback, a staged multi-file commit and a directory scan that must not hide a
# read error. Everything is synthetic and confined to the scenario sandbox.
LOCK_NAME = '.mutation.lock'
SHARED_MANIFEST = 'data/manifest.json'


def _write_text(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def _tree_digest(root):
    """Every file below `root` as relative posix path -> sha256 of its bytes."""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()}


def _snapshot_tree(base):
    """Byte-for-byte copy of a tree, so a rollback can be compared exactly."""
    return {path.relative_to(base).as_posix(): path.read_bytes()
            for path in sorted(base.rglob('*')) if path.is_file()}


def _restore_tree(base, snapshot):
    """Restore a tree exactly: rewrite every snapshot file, delete everything else.

    Deleting the extra files is the part a "copy the files I remember" rollback
    forgets; leaving them behind is what this fixture exists to catch.
    """
    for path in sorted(base.rglob('*'), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() and path.relative_to(base).as_posix() not in snapshot:
            path.unlink()
    for path in sorted(base.rglob('*'), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    for rel, payload in snapshot.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _residue(base, snapshot):
    """Files present now that the snapshot does not know about."""
    return sorted(rel for rel in _tree_digest(base) if rel not in snapshot)


def _read_manifest(root):
    return json.loads((root / SHARED_MANIFEST).read_text(encoding='utf-8'))


def _write_manifest(root, payload):
    path = root / SHARED_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')


def _bump_manifest(root, actor, pause=None):
    """One read-modify-write cycle; `pause` widens the window a lock must close."""
    payload = _read_manifest(root)
    if pause is not None:
        pause()
    payload['count'] += 1
    payload['writers'].append(actor)
    _write_manifest(root, payload)


class _MutationLock:
    """A lock file that refuses a second holder: that refusal *is* mutual exclusion."""

    def __init__(self, root, holder):
        self.path = root / LOCK_NAME
        self.holder = holder

    def __enter__(self):
        if self.path.exists():
            raise RuntimeError(f'LOCK_HELD: {self.path.name} is already held by '
                               f'{self.path.read_text(encoding="utf-8")}')
        self.path.write_text(self.holder, encoding='utf-8')
        return self

    def __exit__(self, *exc):
        if self.path.is_file() and self.path.read_text(encoding='utf-8') == self.holder:
            self.path.unlink()
        return False


def _bump_guarded(root, actor):
    """The guarded call site: the read-modify-write runs inside the lock."""
    with _MutationLock(root, actor):
        _bump_manifest(root, actor)


RMW_HELPER = '_bump_manifest'
SHARED_STATE_SOURCE = '''
def read_manifest(path):
    return json.loads(path.read_text())


def write_manifest(path, payload):
    path.write_text(json.dumps(payload, sort_keys=True))


def _bump_manifest(root, actor):
    payload = read_manifest(root)
    payload["count"] += 1
    write_manifest(root, payload)


def update_import(root):
    with mutation_lock(root):
        _bump_manifest(root, "import")


def update_autosave(root):
    _bump_manifest(root, "autosave")


def update_manual(root):
    with mutation_lock(root):
        _bump_manifest(root, "manual")
'''


def _call_site_findings(source, helper=RMW_HELPER):
    """Every function performing the shared-state cycle, and whether it holds the lock.

    This is a deliberately small AST check over a synthetic module, not a general
    call-site finder: it sees one helper name in one file. Whether a real project
    listed *all* of its call sites stays a reviewer question.
    """
    findings = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = [call for call in ast.walk(node)
                 if isinstance(call, ast.Call) and getattr(call.func, 'id', '') == helper]
        if not calls:
            continue
        guarded = any(isinstance(inner, ast.With)
                      and 'lock' in ast.unparse(inner.items[0].context_expr).lower()
                      for inner in ast.walk(node))
        findings.append({'call_site': node.name, 'guarded': guarded})
    findings.sort(key=lambda item: item['call_site'])
    return findings


COMMIT_STAGES = ('write-a', 'write-b', 'write-c')


def _stage_report(root, fail_at=2, claim_complete=False):
    """Apply a multi-file change stage by stage and report what really happened.

    A failure after stage 1 leaves stage 1 on disk. The honest report says so,
    names the failed stage and the backup, and does not claim a rollback that was
    never performed.
    """
    data, backup = root / 'data', root / 'backup'
    data.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=True)
    completed, failed = [], None
    for index, stage in enumerate(COMMIT_STAGES, 1):
        if index == fail_at:
            failed = stage
            break
        target = data / f'{stage}.txt'
        target.write_text(stage, encoding='utf-8')
        shutil.copy2(target, backup / target.name)
        completed.append(stage)
    return {
        'completed_stages': completed,
        'failed_stage': failed,
        'side_effects': sorted(path.name for path in data.iterdir()),
        'backup': 'backup/',
        'rollback': 'COMPLETE' if claim_complete else 'NONE',
    }


def _scan_entries(directory, swallow=False):
    """Read every directory entry; `swallow` hides an unreadable one behind success."""
    processed, errors, skipped = [], [], []
    paths = sorted(directory.iterdir())
    for path in paths:
        try:
            processed.append({'name': path.name, 'text': path.read_text(encoding='utf-8')})
        except OSError as exc:
            if swallow:
                skipped.append(path.name)
                continue
            errors.append(f'unreadable entry: {path.name} ({type(exc).__name__})')
    failed = bool(errors)
    return {'status': 'FAILED' if failed else 'OK', 'processed': len(processed),
            'total': len(paths), 'errors': errors, 'skipped': skipped}


# --- architecture-contract fixtures (adapter isolation, shared service) -----
# The six rules in docs/architecture/agentmgr-contract-rules.md are exercised on
# the *real* checker: a synthetic tree is written to the sandbox, the optional
# Architecture Contract (frozen by #47, implemented by #48) is asked to judge it,
# and the JSON report is the evidence. The semantic rules (shared application
# service, mock versus real evidence, terminal states, capability claims) cannot
# be proven by static analysis, so they run as small contract tests here and are
# labelled as such. Nothing read or written outside the scenario sandbox.
ARCH_PACKAGE = 'agentorch_architecture'
ARCH_EXPECTED_MODULES = ('adapter-hermes', 'application', 'domain',
                         'entrypoint-api', 'entrypoint-mcp')
SYNTHETIC_TOP_PACKAGE = 'src'
TERMINAL_STATES = ('OK', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'UNKNOWN')
EVIDENCE_KINDS = ('MOCK', 'REAL_RUNTIME')
CAPABILITY_EVIDENCE_KINDS = ('PROBE', 'STARTUP_OK', 'DESIGN_DOC')
PROBE_TIMESTAMP = '2026-10-26T00:00:00Z'

AGM_FILES = {
    'src/domain/rules.py':
        'def decide(request):\n'
        '    return {"amount": request["amount"] * 2}\n',
    'src/app/service.py':
        'from src.domain import rules\n'
        '\n'
        '\n'
        'def plan(request):\n'
        '    return rules.decide(request)\n',
    'src/adapters/hermes/api.py':
        'from src.domain import rules\n'
        '\n'
        '\n'
        'class HermesAdapter:\n'
        '    def decide(self, request):\n'
        '        return rules.decide(request)\n',
    'src/adapters/hermes/runtime/session.py':
        'FRAMEWORK_SESSION = object()\n',
    'src/entrypoints/api/handler.py':
        'from src.app import service\n'
        '\n'
        '\n'
        'def handle(request):\n'
        '    return service.plan(request)\n',
    'src/entrypoints/mcp/handler.py':
        'from src.app import service\n'
        '\n'
        '\n'
        'def handle(request):\n'
        '    return service.plan(request)\n',
}

# The defect: the application service reaches into the adapter's private runtime.
SERVICE_IMPORTS_PRIVATE = (
    'from src.adapters.hermes.runtime import session\n'
    'from src.domain import rules\n'
    '\n'
    '\n'
    'def plan(request):\n'
    '    return rules.decide(request)\n')

# The defect, semantic form: the transport re-implements the rule inline. It has
# no import edge at all, so a dependency check cannot see it.
MCP_INLINE_DECISION = (
    'def handle(request):\n'
    '    return {"amount": request["amount"] * 2 + 1}\n')

# The defect, structural form: the same fork written as a direct domain call,
# which the frozen FORBIDDEN_EDGE rule can block.
MCP_IMPORTS_DOMAIN = (
    'from src.domain import rules\n'
    '\n'
    '\n'
    'def handle(request):\n'
    '    return rules.decide(request)\n')

AGM_MODULES = [
    {'module_id': 'domain', 'paths': ['src/domain/'],
     'responsibilities': ['domain decisions and owned state'],
     'public_interfaces': [{'name': 'src.domain.rules', 'kind': 'python_module',
                            'stability': 'stable'}]},
    {'module_id': 'application', 'paths': ['src/app/'],
     'responsibilities': ['single application service shared by every transport'],
     'public_interfaces': [{'name': 'src.app.service', 'kind': 'python_module',
                            'stability': 'stable'}]},
    {'module_id': 'adapter-hermes', 'paths': ['src/adapters/hermes/'],
     'responsibilities': ['runtime adapter that hides its framework internals'],
     'public_interfaces': [{'name': 'src.adapters.hermes.api', 'kind': 'python_module',
                            'stability': 'additive_only'}],
     'private_paths': ['src/adapters/hermes/runtime/']},
    {'module_id': 'entrypoint-api', 'paths': ['src/entrypoints/api/'],
     'responsibilities': ['HTTP transport: protocol translation only'],
     'public_interfaces': [{'name': 'plan:http', 'kind': 'http_api', 'stability': 'stable'}]},
    {'module_id': 'entrypoint-mcp', 'paths': ['src/entrypoints/mcp/'],
     'responsibilities': ['event transport: protocol translation only'],
     'public_interfaces': [{'name': 'plan:event', 'kind': 'event', 'stability': 'stable'}]},
]

AGM_RULES = [
    {'rule_id': 'ARCH-AGM-NO-CYCLE', 'kind': 'NO_CYCLE', 'severity': 'ERROR',
     'enabled': True, 'description': 'modules must not form dependency cycles'},
    {'rule_id': 'ARCH-AGM-ENTRY-SHARED', 'kind': 'FORBIDDEN_EDGE', 'severity': 'ERROR',
     'enabled': True,
     'description': 'transport entry points call the shared application service, never '
                    'the domain or a concrete adapter'},
    {'rule_id': 'ARCH-AGM-ADAPTER-PRIVATE', 'kind': 'PRIVATE_ACCESS', 'severity': 'ERROR',
     'enabled': True,
     'description': 'core modules never import an adapter private runtime path'},
]

AGM_BOUNDARIES = [
    {'boundary_id': 'BND-DOMAIN', 'kind': 'domain', 'members': ['domain']},
    {'boundary_id': 'BND-APP', 'kind': 'application', 'members': ['application']},
    {'boundary_id': 'BND-ADAPTER', 'kind': 'adapter', 'members': ['adapter-hermes']},
    {'boundary_id': 'BND-TRANSPORT', 'kind': 'layer',
     'members': ['entrypoint-api', 'entrypoint-mcp']},
]

AGM_INVARIANTS = [
    {'invariant_id': 'INV-AGM-ENTRY-EDGE',
     'statement': 'no transport entry point reaches the domain or a concrete adapter '
                  'directly; every request goes through the application service',
     'checked_by': 'STATIC_RULE', 'severity': 'ERROR',
     'rule_ids': ['ARCH-AGM-ENTRY-SHARED']},
    {'invariant_id': 'INV-AGM-ADAPTER-ISOLATION',
     'statement': 'the core modules never import an adapter private runtime path',
     'checked_by': 'STATIC_RULE', 'severity': 'ERROR',
     'rule_ids': ['ARCH-AGM-ADAPTER-PRIVATE']},
    {'invariant_id': 'INV-AGM-SHARED-DECISION',
     'statement': 'both transports return the same decision for the same request',
     'checked_by': 'CONTRACT_TEST', 'severity': 'ERROR',
     'notes': 'the checker cannot run the project test suite; the shared contract test '
              'result has to be attached as its own evidence'},
]


def _agm_contract_data():
    return {
        'schema_version': '1.0',
        'contract_version': '1.0.0',
        'project_name': 'agentmgr-alignment-fixture',
        'enforcement_mode': 'ENFORCE',
        'modules': AGM_MODULES,
        'dependencies': {
            'allowed': [
                {'from': 'entrypoint-api', 'to': 'application',
                 'reason': 'the HTTP transport calls the shared application service'},
                {'from': 'entrypoint-mcp', 'to': 'application',
                 'reason': 'the event transport calls the shared application service'},
                {'from': 'application', 'to': 'domain',
                 'reason': 'the application service orchestrates domain rules'},
                {'from': 'adapter-hermes', 'to': 'domain',
                 'reason': 'the adapter implements the domain port'},
            ],
            'forbidden': [
                {'from': 'entrypoint-api', 'to': 'domain',
                 'reason': 'an entry point must not re-implement a business rule',
                 'rule_id': 'ARCH-AGM-ENTRY-SHARED'},
                {'from': 'entrypoint-mcp', 'to': 'domain',
                 'reason': 'an entry point must not re-implement a business rule',
                 'rule_id': 'ARCH-AGM-ENTRY-SHARED'},
                {'from': 'entrypoint-api', 'to': 'adapter-hermes',
                 'reason': 'an entry point must not bind a concrete adapter',
                 'rule_id': 'ARCH-AGM-ENTRY-SHARED'},
                {'from': 'entrypoint-mcp', 'to': 'adapter-hermes',
                 'reason': 'an entry point must not bind a concrete adapter',
                 'rule_id': 'ARCH-AGM-ENTRY-SHARED'},
            ],
        },
        'boundaries': AGM_BOUNDARIES,
        'invariants': AGM_INVARIANTS,
        'rules': AGM_RULES,
        'baseline': {'frozen_at': '2026-01-01T00:00:00Z', 'frozen_by': 'fixture'},
    }


def _agm_tree(root, *, core_imports_private=False, mcp_bypass=None):
    """Write the synthetic architecture tree; `mcp_bypass` is None / inline / import."""
    files = dict(AGM_FILES)
    if core_imports_private:
        files['src/app/service.py'] = SERVICE_IMPORTS_PRIVATE
    if mcp_bypass == 'inline':
        files['src/entrypoints/mcp/handler.py'] = MCP_INLINE_DECISION
    elif mcp_bypass == 'import':
        files['src/entrypoints/mcp/handler.py'] = MCP_IMPORTS_DOMAIN
    for relative, text in files.items():
        _write_text(root, relative, text)
    return files


def _write_agm_contract(root, data=None):
    path = root / 'docs' / 'architecture' / 'contract.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data if data is not None else _agm_contract_data(),
                               indent=2) + '\n', encoding='utf-8')
    return path


def _load_architecture():
    """Import scripts/architecture as a package (once per process)."""
    if ARCH_PACKAGE in sys.modules:
        return sys.modules[ARCH_PACKAGE]
    base = SCRIPTS / 'architecture'
    init = base / '__init__.py'
    if not init.is_file():
        raise ToolError(f'architecture package not found at {base}')
    spec = importlib.util.spec_from_file_location(
        ARCH_PACKAGE, init, submodule_search_locations=[str(base)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[ARCH_PACKAGE] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - a missing checker is a tool error
        sys.modules.pop(ARCH_PACKAGE, None)
        raise ToolError(f'architecture: cannot import {base}: {exc}') from exc
    return module


def _arch_modules():
    _load_architecture()
    return tuple(importlib.import_module(f'{ARCH_PACKAGE}.{name}')
                 for name in ('contract', 'rules', 'report'))


def _arch_check(root):
    """Run the real checker on a synthetic tree and return its JSON report."""
    contract_module, rules_module, report_module = _arch_modules()
    loaded = contract_module.load(root)
    executed = None
    if loaded['contract'] is not None:
        # Python fixtures only: the Rust adapter is neither exercised nor claimed.
        executed = rules_module.run(loaded['contract'], root, adapters_enabled=('python',))
    return report_module.build_report(root, loaded, executed, HEAD_SHA, 'explicit', ('python',))


def _load_synthetic(root, names):
    """Import synthetic modules from the sandbox (plain files, namespace packages)."""
    root = str(root)
    sys.path.insert(0, root)
    importlib.invalidate_caches()
    try:
        modules = [importlib.import_module(name) for name in names]
    except Exception as exc:  # noqa: BLE001 - a broken fixture is a scenario failure
        raise ScenarioFailed(f'synthetic module import failed: {exc}') from None
    finally:
        for name in [key for key in sys.modules
                     if key == SYNTHETIC_TOP_PACKAGE
                     or key.startswith(SYNTHETIC_TOP_PACKAGE + '.')]:
            sys.modules.pop(name, None)
        try:
            sys.path.remove(root)
        except ValueError:
            pass
    return modules


def _transport_behaviour(api_plan, mcp_plan, requests):
    """Shared contract test: the same request must produce the same decision."""
    differences = []
    for request in requests:
        api, mcp = api_plan(request), mcp_plan(request)
        if api != mcp:
            differences.append({'request': request, 'api': api, 'mcp': mcp})
    return {'requests': len(requests), 'differences': differences, 'agree': not differences}


def _adapter_contract_run(evidence_kind, *, failing=None):
    """Run the shared adapter contract suite against a synthetic implementation."""
    implementation = {name: (lambda: 'PASS') for name in ('create', 'cancel', 'status')}
    if failing:
        implementation[failing] = lambda: 'FAIL'
    checks = {name: implementation[name]() for name in implementation}
    return {'evidence_kind': evidence_kind, 'checks': checks,
            'all_pass': all(value == 'PASS' for value in checks.values())}


def _verification_status(run):
    """What the run establishes: a mock run cannot establish real behaviour."""
    if run['evidence_kind'] == 'REAL_RUNTIME' and run['all_pass']:
        return 'PASS'
    return 'UNKNOWN'


def _claim_findings(run, claimed):
    """The evidence label must not claim more than the run supports."""
    if claimed not in EVIDENCE_KINDS:
        return [f'unknown evidence kind {claimed!r}']
    findings = []
    if not run['all_pass']:
        findings.append('the shared adapter contract suite did not pass; '
                        'nothing may be claimed from it')
    if claimed == 'REAL_RUNTIME' and run['evidence_kind'] != 'REAL_RUNTIME':
        findings.append(f'claim exceeds evidence: {run["evidence_kind"]} results reported as '
                        'REAL_RUNTIME')
    return findings


class _Terminal(RuntimeError):
    code = 'DISPATCH_ERROR'


class _Failed(_Terminal):
    code = 'DISPATCH_FAILED'


class _Cancelled(_Terminal):
    code = 'DISPATCH_CANCELLED'


class _TimedOut(_Terminal):
    code = 'DISPATCH_TIMED_OUT'


class _Unknown(_Terminal):
    code = 'DISPATCH_UNKNOWN'


_TERMINAL_ERRORS = {'FAILED': _Failed, 'CANCELLED': _Cancelled,
                    'TIMED_OUT': _TimedOut, 'UNKNOWN': _Unknown}


def _dispatch_outcome(outcome, *, collapse=False):
    """Result record for a dispatch terminal state; `collapse` is the defect."""
    if outcome == 'OK':
        return {'outcome': 'OK', 'success': True, 'code': None}
    if collapse:
        # The defect: one generic error covers failure, cancellation, timeout and
        # "we do not know", and "unknown" is rewritten as a failure.
        return {'outcome': 'FAILED', 'success': False, 'code': 'DISPATCH_ERROR'}
    return {'outcome': outcome, 'success': False, 'code': _TERMINAL_ERRORS[outcome].code}


def _terminal_findings(results):
    """Terminal-state contract: distinct codes, never upgraded to success."""
    findings = []
    codes = [result['code'] for result in results if result['code']]
    expected = len(TERMINAL_STATES) - 1  # every non-success state has its own code
    if len(set(codes)) < expected:
        findings.append(f'{expected} non-success terminal states collapse into '
                        f'{len(set(codes))} code(s): {", ".join(sorted(set(codes)))}')
    missing = [outcome for outcome in TERMINAL_STATES
               if outcome not in {result['outcome'] for result in results}]
    if missing:
        findings.append('undistinguishable terminal state(s): ' + ', '.join(missing))
    upgraded = [result['outcome'] for result in results
                if result['outcome'] != 'OK' and result['success']]
    if upgraded:
        findings.append('non-success terminal reported as success: ' + ', '.join(upgraded))
    return findings


def _capability_record(capability, status, evidence, scope):
    return {'capability': capability, 'status': status, 'evidence': list(evidence),
            'scope': scope}


def _capability_findings(record):
    """A capability claim is PASS only when it is bound to evidence and a scope."""
    if record['status'] != 'PASS':
        return []  # a non-PASS claim is never silently upgraded to a pass
    findings = []
    evidence = record['evidence']
    if not evidence:
        findings.append(f'PASS without evidence: {record["capability"]} has no probe record')
    for item in evidence:
        if item.get('kind') not in CAPABILITY_EVIDENCE_KINDS:
            findings.append(f'unknown evidence kind {item.get("kind")!r}')
        elif item.get('kind') != 'PROBE':
            findings.append(f'PASS based on {item.get("kind")}: that is not evidence of '
                            f'{record["capability"]}')
        elif not all(item.get(key) for key in ('probe_id', 'probed_at', 'environment')):
            findings.append('probe evidence is missing probe_id / probed_at / environment')
        elif item.get('capability') != record['capability']:
            findings.append(f'probe covered {item.get("capability")!r}, the claim is '
                            f'{record["capability"]!r}')
    if not record['scope'] or record['scope'] == ['*']:
        findings.append('PASS without a specific scope: the claim does not say what was '
                        'verified')
    return findings


SYNTHETIC_TEST_MODULE = '''
import unittest

RAN = []


class SyntheticTests(unittest.TestCase):
    def test_first_passes(self):
        RAN.append('first')

    def test_second_raises(self):
        RAN.append('second')
        raise ZeroDivisionError('synthetic non-assertion failure')

    def test_third_passes(self):
        RAN.append('third')
'''


# --------------------------------------------------------------------------- #
# Group A - governance / authorization
# --------------------------------------------------------------------------- #
def scenario_a1(ctx):
    """Positive control: a legal packet and a legal approval cycle both pass."""
    rows = [_row(_canonical(ctx)[0], ac='AC-1', actual='200 authorized writes succeeded'),
            _row(_canonical(ctx)[0], ac='AC-2', actual='12 writes after revocation returned 403')]
    text = _packet(ctx, [('x', 'AC-1', 'an authorized caller can write'),
                         ('x', 'AC-2', 'a revoked caller is refused')], rows)
    _expect_clean(_packet_errors(ctx, text), 'legal packet')

    root = _project_root(ctx)
    _add(ctx, root, 'TASK-A1', ['src/a1.py'])
    _ready(ctx, root, 'TASK-A1')
    _dispatch(ctx, root, 'TASK-A1')
    _status(ctx, root, 'TASK-A1', 'IN_PROGRESS')
    _status(ctx, root, 'TASK-A1', 'REVIEW_READY', head_sha=HEAD_SHA)
    _status(ctx, root, 'TASK-A1', 'MASTER_REVIEW')
    _status(ctx, root, 'TASK-A1', 'APPROVED', head_sha=HEAD_SHA)
    _status(ctx, root, 'TASK-A1', 'MERGED', merge_sha=MERGE_SHA)
    _status(ctx, root, 'TASK-A1', 'VERIFIED')
    row = _task_row(ctx, root, 'TASK-A1')
    _require(row['status'] == 'VERIFIED', f'legal cycle did not reach VERIFIED (got {row["status"]})')
    _require(row['approved_sha'] == HEAD_SHA, 'approval SHA was not bound to the approved head')
    _require(_count(ctx, root, 'SELECT COUNT(*) FROM locks WHERE task_id=?', ('TASK-A1',)) == 0,
             'path locks were not released on VERIFIED')
    return ['packet: 0 findings over 2 acceptance criteria',
            'legal cycle: PLANNED -> VERIFIED with approval bound to the current head',
            'locks: 0 remaining after VERIFIED']


def scenario_a2(ctx):
    """Authorization revoked: the AC cannot stay marked as met."""
    fields = _canonical(ctx)[0]
    rows = [_row(fields, ac='AC-1', actual='write accepted before revocation'),
            _row(fields, ac='AC-2', status='FAIL',
                 actual='grant revoked at 10:02Z; 12 writes returned 403')]
    text = _packet(ctx, [('x', 'AC-1', 'an authorized caller can write'),
                        ('x', 'AC-2', 'a revoked caller is refused')], rows)
    finding = _expect_finding(_packet_errors(ctx, text),
                             'AC-2 is marked as met but has FAIL evidence', 'revoked grant')
    return [f'gate fired: {finding}']


def scenario_a3(ctx):
    """Audit context missing: an AC without any evidence row cannot pass."""
    fields = _canonical(ctx)[0]
    text = _packet(ctx, [('x', 'AC-1', 'the write is audited'),
                         ('x', 'AC-2', 'the audit record names the actor')],
                   [_row(fields, ac='AC-1', actual='audit row written')])
    finding = _expect_finding(_packet_errors(ctx, text),
                             'AC-2 has no evidence item', 'missing evidence')
    return [f'gate fired: {finding}']


def scenario_a4(ctx):
    """An empty acceptance criterion is not a checkable statement."""
    fields = _canonical(ctx)[0]
    text = _packet(ctx, [('x', 'AC-1', ''), ('x', 'AC-2', 'the write is audited')],
                   [_row(fields, ac='AC-1'), _row(fields, ac='AC-2')])
    finding = _expect_finding(_packet_errors(ctx, text),
                             'AC-1 has no checkable statement', 'empty AC')
    return [f'gate fired: {finding}']


def scenario_a5(ctx):
    """NOT_RUN dressed up as PASS is rejected, not counted as passing."""
    fields = _canonical(ctx)[0]
    text = _packet(ctx, [('x', 'AC-1', 'the write is audited')],
                   [_row(fields, ac='AC-1', status='PASS',
                         actual='suite not run: CI was unavailable')])
    finding = _expect_finding(_packet_errors(ctx, text),
                             'is PASS but reports not-run/blocked evidence', 'NOT_RUN as PASS')
    return [f'gate fired: {finding}']


def scenario_a6(ctx):
    """Duplicate write request and concurrent state change are both refused."""
    root = _project_root(ctx)
    _add(ctx, root, 'TASK-A6A', ['src/shared.py'])
    _add(ctx, root, 'TASK-A6B', ['src/shared.py'])
    _ready(ctx, root, 'TASK-A6A')
    _dispatch(ctx, root, 'TASK-A6A')
    duplicate = _expect_refused(lambda: _dispatch(ctx, root, 'TASK-A6A'),
                                'only READY tasks can be dispatched', 'duplicate dispatch')
    concurrent = _expect_refused(lambda: _ready(ctx, root, 'TASK-A6B'),
                                 'path conflict', 'concurrent claim on the same path')
    _require(_count(ctx, root, 'SELECT COUNT(*) FROM locks WHERE task_id=?', ('TASK-A6B',)) == 0,
             'the refused task ended up holding a path lock')
    return [f'duplicate write: {duplicate}', f'concurrent status change: {concurrent}',
            'refused task holds 0 path locks']


def scenario_a7(ctx):
    """An executor cannot self-approve or skip the review states."""
    root = _project_root(ctx)
    _add(ctx, root, 'TASK-A7', ['src/a7.py'])
    _ready(ctx, root, 'TASK-A7')
    _dispatch(ctx, root, 'TASK-A7')
    approve = _expect_refused(lambda: _status(ctx, root, 'TASK-A7', 'APPROVED', head_sha=HEAD_SHA),
                              'illegal transition DISPATCHED -> APPROVED', 'self-approval')
    verify = _expect_refused(lambda: _status(ctx, root, 'TASK-A7', 'VERIFIED'),
                             'illegal transition DISPATCHED -> VERIFIED', 'self-verification')
    row = _task_row(ctx, root, 'TASK-A7')
    _require(row['status'] == 'DISPATCHED', f'the task moved despite the refusal ({row["status"]})')
    return [f'self-approval: {approve}', f'self-verification: {verify}',
            'task stayed DISPATCHED, approved_sha empty']


# --------------------------------------------------------------------------- #
# Group B - migration / versioning
# --------------------------------------------------------------------------- #
def scenario_b1(ctx):
    """Positive control: migration is idempotent and version-isolated."""
    path = ctx.sandbox / 'roles.json'
    _write_records(path, LEGACY_RECORDS)
    first = _migrate(_read_records(path))
    _write_records(path, first)
    path.with_suffix('.complete').write_text(_digest(first), encoding='utf-8')
    _expect_clean(_verify_migration(path), 'first migration')

    second = _migrate(_read_records(path))
    _write_records(path, second)
    path.with_suffix('.complete').write_text(_digest(second), encoding='utf-8')
    _expect_clean(_verify_migration(path), 'rerun')
    _require(_digest(first) == _digest(second), 'the rerun changed the artifact digest')
    return [f'migration: {len(first)} records upgraded {LEGACY_VERSION} -> {TARGET_VERSION}',
            f'rerun digest unchanged: {_digest(first)[:16]}',
            'verification: 0 findings (count / version / ids / completion marker)']


def scenario_b2(ctx):
    """A migration interrupted halfway must be visible, not silently accepted."""
    path = ctx.sandbox / 'roles.json'
    _write_records(path, LEGACY_RECORDS)
    backup = _read_records(path)
    _write_records(path, _migrate(backup)[:1])  # crash after the first record
    findings = _verify_migration(path)
    count_finding = _expect_finding(findings, 'partial migration', 'half-written artifact')
    _expect_finding(findings, 'completion marker missing', 'unclosed migration')

    _write_records(path, backup)
    _write_records(path, _migrate(_read_records(path)))
    path.with_suffix('.complete').write_text(_digest(_read_records(path)), encoding='utf-8')
    _expect_clean(_verify_migration(path), 'recovery from the backup')
    return [f'gate fired: {count_finding}', 'gate fired: completion marker missing',
            'recovery: artifact restored from the synthetic backup and verified']


def scenario_b3(ctx):
    """Mixing two rule versions inside one target set is a version isolation break."""
    path = ctx.sandbox / 'roles.json'
    records = _migrate(LEGACY_RECORDS)
    records[1] = dict(records[1], version=LEGACY_VERSION)  # one legacy row survives
    _write_records(path, records)
    path.with_suffix('.complete').write_text(_digest(records), encoding='utf-8')
    finding = _expect_finding(_verify_migration(path), 'version isolation broken',
                              'mixed versions in the target set')
    return [f'gate fired: {finding}']


def scenario_b4(ctx):
    """A 'migration completed' claim is contradicted by the missing artifact."""
    fields = _canonical(ctx)[0]
    text = _packet(ctx, [('x', 'AC-1', '旧格式数据已升级到目标版本')],
                   [_row(fields, ac='AC-1', actual='2024 产物已生成，迁移完成')])
    _expect_clean(_packet_errors(ctx, text), 'claim alone is structurally valid')

    missing = _verify_migration(ctx.sandbox / 'absent.json')
    finding = _expect_finding(missing, 'migration artifact missing', 'artifact check')
    return ['packet: the claim is structurally well formed (this is why a claim is not evidence)',
            f'artifact check contradicts the claim: {finding}']


# --------------------------------------------------------------------------- #
# Group C - cross-module closeout
# --------------------------------------------------------------------------- #
def scenario_c1(ctx):
    """Positive control: the frozen rule is wired and the event chain closes."""
    events = _run_turn()
    _expect_clean(_check_turn(events, actor='player-1', owner='player-1'), 'wired turn')
    return [f'turn events: {[event["type"] for event in events]}',
            'invariants: rule wired, ownership honoured, commit barrier first']


def scenario_c2(ctx):
    """A frozen rule that is never called leaves no event, so the chain is incomplete."""
    events = _run_turn(wire_rule=False)
    finding = _expect_finding(_check_turn(events, actor='player-1', owner='player-1'),
                              'frozen rule not wired', 'unwired rule')
    return [f'turn events: {[event["type"] for event in events]}', f'gate fired: {finding}']


def scenario_c3(ctx):
    """Ownership check missing: another actor resolves a unit it does not own."""
    events = _run_turn(actor='player-2', owner='player-1', enforce_ownership=False)
    finding = _expect_finding(_check_turn(events, actor='player-2', owner='player-1'),
                              'ownership gap', 'ownership check')
    return [f'gate fired: {finding}']


def scenario_c4(ctx):
    """Event barrier missing: the change event is emitted before the commit."""
    events = _run_turn(barrier=False)
    finding = _expect_finding(_check_turn(events, actor='player-1', owner='player-1'),
                              'event barrier missing', 'barrier')
    return [f'turn events: {[event["type"] for event in events]}', f'gate fired: {finding}']


def scenario_c5(ctx):
    """A non-assertion exception is recorded and the suite keeps running."""
    namespace = {'__name__': 'synthetic_delivery_flow'}
    exec(compile(SYNTHETIC_TEST_MODULE, '<synthetic-tests>', 'exec'), namespace)  # noqa: S102
    suite = unittest.TestLoader().loadTestsFromTestCase(namespace['SyntheticTests'])
    result = unittest.TestResult()
    suite.run(result)
    _require(result.testsRun == 3, f'expected 3 tests to run, got {result.testsRun}')
    _require(len(result.errors) == 1,
             f'expected exactly one non-assertion error, got {len(result.errors)}')
    _require(len(result.failures) == 0, 'a non-assertion exception was recorded as a failure')
    _require('ZeroDivisionError' in result.errors[0][1], 'the traceback was not preserved')
    _require(namespace['RAN'] == ['first', 'second', 'third'],
             f'the suite stopped early: ran {namespace["RAN"]}')
    return [f'testsRun={result.testsRun}, errors={len(result.errors)}, failures=0',
            'traceback preserved: ZeroDivisionError',
            f'later test still executed: {namespace["RAN"]}']


# --------------------------------------------------------------------------- #
# Group C, second family - shared state, locking and recovery
# --------------------------------------------------------------------------- #
def scenario_c6(ctx):
    """Positive control: guarded call sites, exact rollback, intact lock, honest scan."""
    root = ctx.sandbox / 'delivery'
    _write_text(root, 'data/a.txt', 'alpha')
    _write_text(root, 'data/nested/b.txt', 'bravo')
    _write_manifest(root, {'count': 0, 'writers': []})
    baseline = _snapshot_tree(root / 'data')
    baseline_digest = _tree_digest(root / 'data')

    _bump_guarded(root, 'import')
    _bump_guarded(root, 'autosave')
    manifest = _read_manifest(root)
    _require(manifest['count'] == 2 and manifest['writers'] == ['import', 'autosave'],
             f'the guarded call sites did not both land: {manifest}')

    # A change that fails half-way is rolled back to the exact baseline tree.
    _write_text(root, 'data/a.txt', 'alpha-changed')
    _write_text(root, 'data/extra.txt', 'delta')
    _restore_tree(root / 'data', baseline)
    tree_matches = _tree_digest(root / 'data') == baseline_digest
    _require(tree_matches, f'rollback left the tree different: {_residue(root / "data", baseline)}')

    # The lock is gone after the operation and can be taken again.
    lock_released = not (root / LOCK_NAME).exists()
    _require(lock_released, 'the lock file survived a completed operation')
    with _MutationLock(root, 'operation-3'):
        refused = _expect_refused(lambda: _MutationLock(root, 'operation-4').__enter__(),
                                  'LOCK_HELD', 'second holder while the lock is live')

    entries = ctx.sandbox / 'entries'
    _write_text(entries, 'ok-1.txt', 'one')
    _write_text(entries, 'ok-2.txt', 'two')
    scan = _scan_entries(entries)
    _require(scan['status'] == 'OK' and not scan['errors'] and not scan['skipped'],
             f'a clean directory scan reported a problem: {scan}')
    _require(scan['processed'] == scan['total'] == 2, f'the scan lost entries: {scan}')

    return ['guarded call sites: count=2, writers=[import, autosave]',
            'tree matches baseline: True (exact rollback, no residue)',
            'lock released: True',
            f'second holder refused while the lock is live: {refused}',
            f'entry scan: {scan["status"]} over {scan["total"]} entries, 0 findings']


def scenario_c7(ctx):
    """One unguarded call site is enough: the shared counter loses an update."""
    root = ctx.sandbox / 'shared'
    _write_manifest(root, {'count': 0, 'writers': []})

    def second_writer():
        _bump_guarded(root, 'autosave')

    # The defect: the autosave call site runs the cycle without taking the lock.
    _bump_manifest(root, 'import', pause=second_writer)
    lossy = _read_manifest(root)
    lost_update = lossy['count'] != 2 or 'autosave' not in lossy['writers']
    _require(lost_update, f'the unguarded interleaving was expected to lose an update: {lossy}')
    _require(lossy['count'] == 1, f'expected count=1 after the lost update, got {lossy["count"]}')

    # The same two call sites, both guarded: exclusion holds and both land.
    _write_manifest(root, {'count': 0, 'writers': []})
    with _MutationLock(root, 'import'):
        refused = _expect_refused(lambda: _MutationLock(root, 'autosave').__enter__(),
                                  'LOCK_HELD', 'second holder while the first call site runs')
        _bump_manifest(root, 'import')
    _bump_guarded(root, 'autosave')
    fixed = _read_manifest(root)
    _require(fixed['count'] == 2 and fixed['writers'] == ['import', 'autosave'],
             f'the guarded call sites did not preserve both updates: {fixed}')

    findings = _call_site_findings(SHARED_STATE_SOURCE)
    unguarded = [item['call_site'] for item in findings if not item['guarded']]
    _require(unguarded == ['update_autosave'],
             f'the call-site inventory did not isolate the defect: {findings}')
    _require(len(findings) == 3, f'expected three call sites to be inventoried, got {findings}')
    return [f'call sites inventoried: {[item["call_site"] for item in findings]}',
            'unguarded call site: update_autosave',
            f'second holder refused while the guarded site runs: {refused}',
            f'lost update: count={lossy["count"]}, writers={lossy["writers"]} '
            '(the autosave increment disappeared)',
            f'guarded rerun: count={fixed["count"]}, writers={fixed["writers"]}']


def scenario_c8(ctx):
    """Rolling back only the remembered files leaves the extra files behind."""
    root = ctx.sandbox / 'recovery'
    _write_text(root, 'data/a.txt', 'alpha')
    _write_text(root, 'data/nested/b.txt', 'bravo')
    baseline = _snapshot_tree(root / 'data')
    baseline_digest = _tree_digest(root / 'data')

    _write_text(root, 'data/a.txt', 'alpha-changed')
    _write_text(root, 'data/new.txt', 'delta')
    _write_text(root, 'data/nested/late.txt', 'echo')

    # The defect: restore the files the backup remembers, forget the new ones.
    for rel, payload in baseline.items():
        (root / 'data' / rel).write_bytes(payload)
    residue = _residue(root / 'data', baseline)
    _require(residue == ['nested/late.txt', 'new.txt'],
             f'expected two residue files, got {residue}')
    _require(_tree_digest(root / 'data') != baseline_digest,
             'the residue did not survive the "rollback", so the defect is not modelled')

    _restore_tree(root / 'data', baseline)
    restored = _tree_digest(root / 'data') == baseline_digest
    _require(restored, f'the exact rollback still differs: {_residue(root / "data", baseline)}')
    return [f'residue after memory-only rollback: {", ".join(residue)}',
            'the tree still differed from the baseline after that rollback',
            'tree matches baseline: True (after restoring the exact snapshot)']


def scenario_c9(ctx):
    """A business rollback that restores the whole directory deletes the lock file."""
    root = ctx.sandbox / 'locks'
    _write_text(root, 'data/a.txt', 'alpha')
    whole_root = _snapshot_tree(root)

    def acquire(holder):
        _MutationLock(root, holder).__enter__()

    def release(holder):
        lock = root / LOCK_NAME
        if lock.is_file() and lock.read_text(encoding='utf-8') == holder:
            lock.unlink()

    # The defect: the snapshot is taken before the lock exists and covers the
    # whole root, so restoring it removes the lock while the operation is live.
    acquire('operation-1')
    _write_text(root, 'data/a.txt', 'alpha-changed')
    _write_text(root, 'data/tmp.txt', 'written-before-the-failure')
    _restore_tree(root, whole_root)
    lock_deleted = not (root / LOCK_NAME).exists()
    _require(lock_deleted, 'the whole-root rollback kept the lock; the defect is not modelled')
    acquirer = _MutationLock(root, 'operation-2')
    acquirer.__enter__()
    second_writer_in = (root / LOCK_NAME).read_text(encoding='utf-8') == 'operation-2'
    _require(second_writer_in, 'the second writer did not take the orphaned lock')
    acquirer.__exit__(None, None, None)

    # The correct order: snapshot the data subtree only, so the lock survives.
    data_baseline = _snapshot_tree(root / 'data')
    data_digest = _tree_digest(root / 'data')
    acquire('operation-1')
    _write_text(root, 'data/tmp.txt', 'written-before-the-failure')
    _restore_tree(root / 'data', data_baseline)
    lock_survives = (root / LOCK_NAME).is_file()
    _require(lock_survives, 'a data-only rollback removed the lock')
    refused = _expect_refused(lambda: acquire('operation-2'), 'LOCK_HELD',
                              'second writer while the lock survives')
    release('operation-1')
    acquire('operation-2')
    release('operation-2')
    _require(_tree_digest(root / 'data') == data_digest,
             f'the data tree did not return to its baseline: '
             f'{_residue(root / "data", data_baseline)}')
    _require(_residue(root / 'data', data_baseline) == [],
             'the data rollback left residue behind')
    return ['lock file deleted by rollback: True',
            'second writer acquired the lock: True (mutual exclusion was lost)',
            f'correct rollback keeps it: lock survives a data rollback: {lock_survives}',
            f'second writer after the fix: {refused}',
            'lock released and reused: True; the data tree is back to its baseline']


def scenario_c10(ctx):
    """A failure after a partial commit must not be reported as a complete rollback."""
    root = ctx.sandbox / 'commit'
    report = _stage_report(root, fail_at=2)
    _require(report['failed_stage'] == 'write-b',
             f'the report does not name the failed stage: {report}')
    _require(report['completed_stages'] == ['write-a'],
             f'the report hides the completed stage: {report}')
    _require(report['side_effects'] == ['write-a.txt'],
             f'the report does not list the side effects: {report}')
    _require(report['rollback'] == 'NONE',
             f'the honest report claimed a rollback it did not perform: {report}')
    _require(report['backup'] == 'backup/',
             f'the report does not say where the backup is: {report}')

    # The defect: the same partial commit, reported as a complete rollback.
    lie_root = ctx.sandbox / 'commit-claim'
    lie = _stage_report(lie_root, fail_at=2, claim_complete=True)
    remaining = sorted(path.name for path in (lie_root / 'data').iterdir())
    contradicted = lie['rollback'] == 'COMPLETE' and bool(remaining)
    _require(contradicted,
             f'the false complete-rollback claim was not contradicted by the tree: {lie}')
    _require(remaining == ['write-a.txt'],
             f'expected exactly the stage-1 side effect, got {remaining}')
    return [f'failed stage: {report["failed_stage"]}',
            f'completed stages: {report["completed_stages"]}; '
            f'side effects: {report["side_effects"]}; rollback: {report["rollback"]}',
            f'backup location reported: {report["backup"]}',
            f'a "complete rollback" claim is contradicted by {len(remaining)} remaining '
            'file(s): True']


def scenario_c11(ctx):
    """An unreadable directory entry hidden behind a success report is a swallowed error."""
    entries = ctx.sandbox / 'scan'
    _write_text(entries, 'ok-1.txt', 'one')
    _write_text(entries, 'ok-2.txt', 'two')
    (entries / 'broken.json').mkdir(parents=True, exist_ok=True)  # cannot be read as a file

    lossy = _scan_entries(entries, swallow=True)
    _require(lossy['skipped'] == ['broken.json'],
             f'the swallowing scan did not skip the unreadable entry: {lossy}')
    _require(lossy['status'] == 'OK',
             f'the swallowing scan already reported a failure: {lossy}')
    contradiction = lossy['status'] == 'OK' and lossy['processed'] != lossy['total']
    _require(contradiction,
             f'the success report is not contradicted by the entry count: {lossy}')

    honest = _scan_entries(entries)
    _require(honest['status'] == 'FAILED',
             f'the corrected scan still reported success: {honest}')
    _require(any('broken.json' in error for error in honest['errors']),
             f'the corrected scan did not name the unreadable entry: {honest}')
    _require(honest['skipped'] == [], 'the corrected scan still swallowed the entry')
    return [f'skipped with a success report: {", ".join(lossy["skipped"])}',
            f'report claims OK while {lossy["total"] - lossy["processed"]} of '
            f'{lossy["total"]} entries were skipped: True',
            f'surface the error instead: {honest["status"]} naming broken.json '
            f'({len(honest["errors"])} error(s), 0 skipped)']


# --------------------------------------------------------------------------- #
# Group C, third family - architecture contract alignment
# --------------------------------------------------------------------------- #
def scenario_c12(ctx):
    """Positive control: one application service, honest labels, no over-claimed PASS."""
    root = ctx.sandbox / 'architecture'
    _agm_tree(root)
    _write_agm_contract(root)
    report = _arch_check(root)
    _require(report['enforcement_mode'] == 'ENFORCE', report['enforcement_mode'])
    _require(report['blocking'] is False, f'a clean tree blocked: {report["findings"]}')
    _require(report['status'] == 'PASS', f'expected PASS, got {report["status"]}: '
                                         f'{report["findings"]}')
    _require(report['counts']['ERROR'] == 0, report['counts'])
    _require(tuple(sorted(report['examined_modules'])) == ARCH_EXPECTED_MODULES,
             f'the report does not state its scope: {report["examined_modules"]}')
    _require(report['uncovered_modules'] == [], report['uncovered_modules'])
    coverage = {entry['invariant_id']: entry['status'] for entry in report['invariants']}
    _require(coverage.get('INV-AGM-ENTRY-EDGE') == 'PASS', coverage)
    _require(coverage.get('INV-AGM-ADAPTER-ISOLATION') == 'PASS', coverage)
    _require(coverage.get('INV-AGM-SHARED-DECISION') == 'UNKNOWN',
             f'a declared contract test was reported as coverage: {coverage}')

    api_handler, mcp_handler = _load_synthetic(
        root, ['src.entrypoints.api.handler', 'src.entrypoints.mcp.handler'])
    requests = [{'amount': 1}, {'amount': 7}]
    behaviour = _transport_behaviour(api_handler.handle, mcp_handler.handle, requests)
    _require(behaviour['agree'], f'the two transports disagree on a clean tree: {behaviour}')

    mock_run = _adapter_contract_run('MOCK')
    _require(_claim_findings(mock_run, 'MOCK') == [],
             f'a mock run may be claimed as mock: {_claim_findings(mock_run, "MOCK")}')
    _require(_verification_status(mock_run) == 'UNKNOWN',
             'a mock run was reported as real verification')

    fixed_terminals = [_dispatch_outcome(outcome) for outcome in TERMINAL_STATES]
    _require(_terminal_findings(fixed_terminals) == [], _terminal_findings(fixed_terminals))

    unprobed = _capability_record('execution_isolation', 'UNKNOWN', [], None)
    _require(_capability_findings(unprobed) == [],
             'an honest UNKNOWN capability claim was rejected')
    probed = _capability_record(
        'execution_isolation', 'PASS',
        [{'kind': 'PROBE', 'probe_id': 'probe-1', 'probed_at': PROBE_TIMESTAMP,
          'environment': 'synthetic fixture', 'capability': 'execution_isolation'}],
        ['single-process sandbox'])
    _require(_capability_findings(probed) == [],
             f'a probed capability claim with a scope was rejected: '
             f'{_capability_findings(probed)}')

    return [f'contract: mode=ENFORCE status={report["status"]} '
            f'ERROR={report["counts"]["ERROR"]} blocking={report["blocking"]}',
            f'scope: examined modules = {", ".join(report["examined_modules"])}; '
            f'uncovered = {report["uncovered_modules"] or "none"}',
            'invariant coverage: entry-edge PASS, adapter-isolation PASS, '
            'shared-decision UNKNOWN (a declared contract test is not coverage)',
            f'shared contract test: both transports agree on {behaviour["requests"]} requests',
            f'mock adapter contract run: claimed MOCK, verification '
            f'{_verification_status(mock_run)} (never real)',
            f'terminal states: {", ".join(sorted({r["code"] for r in fixed_terminals if r["code"]}))}',
            'capability claim: UNKNOWN accepted; probed + scoped PASS accepted']


def scenario_c13(ctx):
    """A core module importing an adapter private symbol is blocked statically."""
    root = ctx.sandbox / 'private-symbol'
    _agm_tree(root, core_imports_private=True)
    _write_agm_contract(root)
    report = _arch_check(root)
    _require(report['blocking'] is True,
             f'the checker did not block a core -> adapter private import: {report["findings"]}')
    hits = [finding for finding in report['findings']
            if finding['rule_id'] == 'ARCH-AGM-ADAPTER-PRIVATE' and finding['status'] == 'ERROR']
    _require(len(hits) == 1, f'expected one PRIVATE_ACCESS error, got {report["findings"]}')
    hit = hits[0]
    _require(hit['module_id'] == 'application' and hit['target_module'] == 'adapter-hermes',
             f'the violation is not locatable: {hit}')
    _require(hit['file'] == 'src/app/service.py' and hit['line'] == 1,
             f'the import location is missing: {hit}')
    _require('src/adapters/hermes/runtime' in hit['message'], hit['message'])
    coverage = {entry['invariant_id']: entry['status'] for entry in report['invariants']}
    _require(coverage.get('INV-AGM-ADAPTER-ISOLATION') == 'ERROR',
             f'the bound invariant did not follow its rule: {coverage}')
    return [f'blocking: {report["blocking"]}; counts: {report["counts"]}',
            f'PRIVATE_ACCESS error: {hit["module_id"]} -> {hit["target_module"]} '
            f'at {hit["file"]}:{hit["line"]}',
            f'invariant INV-AGM-ADAPTER-ISOLATION coverage: '
            f'{coverage.get("INV-AGM-ADAPTER-ISOLATION")}']


def scenario_c14(ctx):
    """Two transports with forked business rules: static edge or shared contract test."""
    requests = [{'amount': 1}, {'amount': 4}]

    # Semantic fork: an inline re-implementation has no import edge, so the
    # dependency checker is blind to it by construction (and must not pretend).
    semantic_root = ctx.sandbox / 'fork-inline'
    _agm_tree(semantic_root, mcp_bypass='inline')
    _write_agm_contract(semantic_root)
    semantic = _arch_check(semantic_root)
    _require(semantic['blocking'] is False,
             'the dependency checker claimed to catch an inline re-implementation')
    coverage = {entry['invariant_id']: entry['status'] for entry in semantic['invariants']}
    _require(coverage.get('INV-AGM-SHARED-DECISION') == 'UNKNOWN',
             f'a declared contract test was reported as coverage: {coverage}')
    api_handler, mcp_handler = _load_synthetic(
        semantic_root, ['src.entrypoints.api.handler', 'src.entrypoints.mcp.handler'])
    behaviour = _transport_behaviour(api_handler.handle, mcp_handler.handle, requests)
    _require(behaviour['agree'] is False,
             'the shared contract test did not catch the forked decision')
    _require(len(behaviour['differences']) == len(requests),
             f'only part of the fork was observed: {behaviour}')

    # Structural fork: the same divergence written as a direct domain call is
    # exactly what FORBIDDEN_EDGE can block.
    structural_root = ctx.sandbox / 'fork-import'
    _agm_tree(structural_root, mcp_bypass='import')
    _write_agm_contract(structural_root)
    structural = _arch_check(structural_root)
    _require(structural['blocking'] is True,
             f'the forbidden edge was not blocked: {structural["findings"]}')
    hits = [finding for finding in structural['findings']
            if finding['rule_id'] == 'ARCH-AGM-ENTRY-SHARED' and finding['status'] == 'ERROR']
    _require(len(hits) == 1, structural['findings'])
    _require(hits[0]['module_id'] == 'entrypoint-mcp'
             and hits[0]['target_module'] == 'domain', hits[0])
    return [f'inline fork: static blocking={semantic["blocking"]} (a dependency check '
            'cannot see it), shared contract test agreement=False over '
            f'{len(behaviour["differences"])}/{behaviour["requests"]} requests',
            f'inline fork: INV-AGM-SHARED-DECISION coverage='
            f'{coverage.get("INV-AGM-SHARED-DECISION")} (declaration is not coverage)',
            f'structural fork: blocking={structural["blocking"]}, '
            f'{hits[0]["module_id"]} -> {hits[0]["target_module"]} at '
            f'{hits[0]["file"]}:{hits[0]["line"]}']


def scenario_c15(ctx):
    """A mock adapter success must never be reported as real runtime verification."""
    mock = _adapter_contract_run('MOCK')
    _require(mock['all_pass'], f'the mock run should pass its shared contract: {mock}')
    over_claim = _claim_findings(mock, 'REAL_RUNTIME')
    _require(any('exceeds evidence' in finding for finding in over_claim),
             f'the mock -> real over-claim was accepted: {over_claim}')
    _require(_verification_status(mock) == 'UNKNOWN',
             'a mock run was upgraded to real verification')

    honest = _claim_findings(mock, 'MOCK')
    _require(honest == [], f'a mock run labelled mock was rejected: {honest}')

    real = _adapter_contract_run('REAL_RUNTIME')
    _require(_claim_findings(real, 'REAL_RUNTIME') == [],
             'a real run labelled real was rejected')
    _require(_verification_status(real) == 'PASS', _verification_status(real))

    broken = _adapter_contract_run('REAL_RUNTIME', failing='cancel')
    _require(_claim_findings(broken, 'REAL_RUNTIME') != [],
             'a failing contract suite still supported a claim')
    return [f'mock run: all_pass={mock["all_pass"]}, claimed MOCK -> no finding; '
            f'verification status {_verification_status(mock)}',
            'mock run claimed REAL_RUNTIME -> ' + over_claim[0],
            f'real run: verification status {_verification_status(real)}',
            'failing contract suite: ' + _claim_findings(broken, 'REAL_RUNTIME')[0]]


def scenario_c16(ctx):
    """Cancellation, timeout, failure and "unknown" must stay distinguishable."""
    collapsed = [_dispatch_outcome(outcome, collapse=True) for outcome in TERMINAL_STATES]
    findings = _terminal_findings(collapsed)
    _require(bool(findings), 'the collapsed terminal states were not reported')
    _require(any('collapse' in finding for finding in findings), findings)
    _require(all(not record['success'] for record in collapsed[1:]),
             'a non-success terminal was recorded as success')
    collapsed_codes = sorted({record['code'] for record in collapsed if record['code']})
    _require(len(collapsed_codes) == 1, collapsed_codes)

    distinct = [_dispatch_outcome(outcome) for outcome in TERMINAL_STATES]
    _require(_terminal_findings(distinct) == [],
             f'the distinct terminal states were rejected: {_terminal_findings(distinct)}')
    codes = sorted({record['code'] for record in distinct if record['code']})
    _require(len(codes) == len(TERMINAL_STATES) - 1, codes)
    _require(all(not record['success'] for record in distinct[1:]),
             'a distinct non-success terminal was recorded as success')
    return [f'collapsed: {len(TERMINAL_STATES) - 1} non-success states -> 1 code '
            f'({", ".join(collapsed_codes)}); reported: {findings[0]}',
            f'distinct: {", ".join(codes)}',
            'no non-success terminal was reported as success in either variant']


def scenario_c17(ctx):
    """A capability may only be PASS when its evidence and scope are attached."""
    unbacked = _capability_record('execution_isolation', 'PASS', [], None)
    unbacked_findings = _capability_findings(unbacked)
    _require(any('without evidence' in finding for finding in unbacked_findings),
             f'PASS without evidence was accepted: {unbacked_findings}')

    startup_only = _capability_record(
        'execution_isolation', 'PASS',
        [{'kind': 'STARTUP_OK', 'probe_id': 'probe-1', 'probed_at': PROBE_TIMESTAMP,
          'environment': 'synthetic fixture', 'capability': 'execution_isolation'}],
        ['single-process sandbox'])
    startup_findings = _capability_findings(startup_only)
    _require(any('not evidence of' in finding for finding in startup_findings),
             f'"startup succeeded" was accepted as isolation evidence: {startup_findings}')

    wildcard = _capability_record(
        'execution_isolation', 'PASS',
        [{'kind': 'PROBE', 'probe_id': 'probe-1', 'probed_at': PROBE_TIMESTAMP,
          'environment': 'synthetic fixture', 'capability': 'execution_isolation'}],
        ['*'])
    wildcard_findings = _capability_findings(wildcard)
    _require(any('scope' in finding for finding in wildcard_findings),
             f'PASS with a wildcard scope was accepted: {wildcard_findings}')

    wrong_probe = _capability_record(
        'cancellation', 'PASS',
        [{'kind': 'PROBE', 'probe_id': 'probe-1', 'probed_at': PROBE_TIMESTAMP,
          'environment': 'synthetic fixture', 'capability': 'execution_isolation'}],
        ['single-process sandbox'])
    wrong_findings = _capability_findings(wrong_probe)
    _require(any('probe covered' in finding for finding in wrong_findings),
             f'a probe for a different capability was accepted: {wrong_findings}')

    honest = _capability_record('execution_isolation', 'UNKNOWN', [], None)
    _require(_capability_findings(honest) == [],
             'an honest UNKNOWN claim was rejected')
    return [f'PASS without evidence -> {len(unbacked_findings)} finding(s): '
            f'{unbacked_findings[0]}',
            f'"startup succeeded" as isolation evidence -> {startup_findings[0]}',
            f'wildcard scope -> {wildcard_findings[0]}',
            f'probe for another capability -> {wrong_findings[0]}',
            'honest UNKNOWN claim: 0 findings (a non-PASS claim is not upgraded)']


def scenario_c18(ctx):
    """Without a contract the same violations stay diagnostic: no inferred rule fires."""
    root = ctx.sandbox / 'unconfigured'
    files = _agm_tree(root, core_imports_private=True, mcp_bypass='import')
    report = _arch_check(root)
    _require(report['contract_path'] is None, report['contract_path'])
    _require(report['enforcement_mode'] == 'OFF', report['enforcement_mode'])
    _require(report['diagnostic_only'] is True, report['diagnostic_only'])
    _require(report['blocking'] is False, 'an unconfigured project was blocked')
    _require(report['counts']['ERROR'] == 0, report['counts'])
    _require(report['counts']['WARNING'] == 0, report['counts'])
    _require(report['status'] == 'NOT_RUN', report['status'])
    _require(report['invariants'] == [], report['invariants'])
    _require(report['examined_modules'] == [], report['examined_modules'])
    inventory = report.get('inventory') or {}
    _require(inventory.get('python_files') == len(files),
             f'the read-only inventory is incomplete: {inventory}')

    # The only difference is the declaration: the same tree with a contract blocks.
    _write_agm_contract(root)
    declared = _arch_check(root)
    _require(declared['blocking'] is True,
             'the same tree was not blocked once the contract was declared')
    return [f'no contract: mode={report["enforcement_mode"]} status={report["status"]} '
            f'blocking={report["blocking"]} ERROR={report["counts"]["ERROR"]} '
            f'WARNING={report["counts"]["WARNING"]}',
            f'read-only inventory: {inventory.get("python_files")} python files, '
            f'0 rules executed',
            f'the same tree with a declared contract: blocking={declared["blocking"]} '
            f'ERROR={declared["counts"]["ERROR"]}']


# --------------------------------------------------------------------------- #
# Group D - orchestration base and evidence decay
# --------------------------------------------------------------------------- #
def scenario_d1(ctx):
    """Positive control: a legal edition with a declared resource closes out cleanly."""
    root = _project_root(ctx, config={'resource_lease_ttl': 3600, 'resource_reclaim_grace': 60})
    edition = ctx.orch.read_project_edition(root)
    _require(edition == 'local', f'expected edition local, got {edition!r}')
    _add(ctx, root, 'TASK-D1', ['src/d1.py'], resources=['db:test/main:exclusive'])
    _ready(ctx, root, 'TASK-D1')
    _dispatch(ctx, root, 'TASK-D1')
    _status(ctx, root, 'TASK-D1', 'IN_PROGRESS')
    _status(ctx, root, 'TASK-D1', 'REVIEW_READY', head_sha=HEAD_SHA)
    _status(ctx, root, 'TASK-D1', 'MASTER_REVIEW')
    _status(ctx, root, 'TASK-D1', 'APPROVED', head_sha=HEAD_SHA)
    _status(ctx, root, 'TASK-D1', 'MERGED', merge_sha=MERGE_SHA)
    _status(ctx, root, 'TASK-D1', 'VERIFIED')
    remaining = _count(ctx, root, "SELECT COUNT(*) FROM resource_locks "
                                 "WHERE task_id=? AND state<>'RELEASED'", ('TASK-D1',))
    held = _count(ctx, root, 'SELECT COUNT(*) FROM resource_locks WHERE task_id=?', ('TASK-D1',))
    _require(remaining == 0, f'resource lock still held after VERIFIED ({remaining})')
    _require(held == 1, f'expected exactly one acquired resource lock row, got {held}')
    return [f'edition: {edition}', 'resource db:test/main:exclusive acquired on dispatch',
            'closed out: 1 lock row, 0 non-RELEASED after VERIFIED']


def scenario_d2(ctx):
    """An illegal, missing or duplicated edition stops scheduling instead of guessing."""
    cases = []
    for label, body in (('missing key', '# Synthetic project\n\nno edition line here\n'),
                        ('illegal value', '# Synthetic project\n\n- `edition`\uFF1A`gitlab`\n'),
                        ('duplicate key', '# Synthetic project\n\n- `edition`\uFF1A`local`\n'
                                          '- `edition`\uFF1A`github`\n')):
        root = ctx.sandbox / f'edition-{label.replace(" ", "-")}'
        root.mkdir(parents=True, exist_ok=True)
        (root/'docs').mkdir(parents=True, exist_ok=True) or (root / 'docs/PROJECT.md').write_text(body, encoding='utf-8')
        message = _expect_refused(lambda root=root: ctx.orch.read_project_edition(root),
                                  'docs/PROJECT.md', label)
        cases.append(f'{label}: {message}')

    broken = ctx.sandbox / 'edition-absent'
    broken.mkdir(parents=True, exist_ok=True)
    cases.append('missing file: ' + _expect_refused(
        lambda: ctx.orch.read_project_edition(broken), 'file not found', 'missing file'))

    github = _project_root(ctx, edition='github')
    cases.append('github scheduling: ' + _expect_refused(
        lambda: ctx.orch.require_local_scheduler(github, 'task dispatch'),
        'cannot run', 'github edition'))
    return cases


def scenario_d3(ctx):
    """A conflicting exclusive resource is denied atomically, leaving no half lock."""
    root = _project_root(ctx, config={'resource_lease_ttl': 3600, 'resource_reclaim_grace': 60})
    _add(ctx, root, 'TASK-D3A', ['src/d3a.py'], resources=['db:test/main:exclusive'])
    _add(ctx, root, 'TASK-D3B', ['src/d3b.py'], resources=['db:test/main:exclusive'])
    _ready(ctx, root, 'TASK-D3A')
    _dispatch(ctx, root, 'TASK-D3A', holder='synthetic-host:1')
    _ready(ctx, root, 'TASK-D3B')
    message = _expect_refused(lambda: _dispatch(ctx, root, 'TASK-D3B', holder='synthetic-host:2'),
                              'MODE_CONFLICT', 'conflicting exclusive resource')
    held = _count(ctx, root, "SELECT COUNT(*) FROM resource_locks "
                             "WHERE task_id='TASK-D3B' AND state<>'RELEASED'")
    locks = _count(ctx, root, "SELECT COUNT(*) FROM locks WHERE task_id='TASK-D3B'")
    denied = _count(ctx, root, "SELECT COUNT(*) FROM resource_lock_events "
                               "WHERE task_id='TASK-D3B' AND event_type='LOCK_DENIED_CONFLICT'")
    status = _task_row(ctx, root, 'TASK-D3B')['status']
    _require(held == 0, f'the refused task keeps {held} resource lock row(s)')
    _require(locks == 0, f'the refused task keeps {locks} path lock(s)')
    _require(denied >= 1, 'the denial left no LOCK_DENIED_CONFLICT audit event')
    _require(status == 'READY', f'the refused task left READY (status {status})')
    return [f'gate fired: {message}', 'refused task: 0 resource locks, 0 path locks, still READY',
            f'audit: {denied} LOCK_DENIED_CONFLICT event(s)']


def scenario_d4(ctx):
    """A new head invalidates the old approval; the stale SHA cannot be merged."""
    root = _project_root(ctx)
    _add(ctx, root, 'TASK-D4', ['src/d4.py'])
    _drive_to_master_review(ctx, root, 'TASK-D4', head_sha=HEAD_SHA)
    _status(ctx, root, 'TASK-D4', 'APPROVED', head_sha=HEAD_SHA)
    _workspace(ctx, root, 'TASK-D4', STALE_SHA)
    row = _task_row(ctx, root, 'TASK-D4')
    _require(row['status'] == 'MASTER_REVIEW',
             f'a new head did not return the task to MASTER_REVIEW (got {row["status"]})')
    _require(row['approved_sha'] == '', 'the stale approval SHA survived the head change')
    merge = _expect_refused(lambda: _status(ctx, root, 'TASK-D4', 'MERGED', merge_sha=MERGE_SHA),
                            'illegal transition MASTER_REVIEW -> MERGED', 'merge after head change')
    stale = _expect_refused(lambda: _status(ctx, root, 'TASK-D4', 'APPROVED', head_sha=HEAD_SHA),
                            'does not match current task head', 'approval reusing the old head')
    return ['new head: status MASTER_REVIEW, approved_sha cleared',
            f'merge refused: {merge}',
            f'old-head approval refused: {stale}']


def scenario_d5(ctx):
    """The review-fix cap is enforced; the fourth round becomes BLOCKED."""
    root = _project_root(ctx, config={'retry_cap': 3})
    _add(ctx, root, 'TASK-D5', ['src/d5.py'])
    _drive_to_master_review(ctx, root, 'TASK-D5')
    for _ in range(3):
        _status(ctx, root, 'TASK-D5', 'IN_PROGRESS')
        _status(ctx, root, 'TASK-D5', 'REVIEW_READY', head_sha=HEAD_SHA)
        _status(ctx, root, 'TASK-D5', 'MASTER_REVIEW')
    _status(ctx, root, 'TASK-D5', 'IN_PROGRESS', note='fourth review-fix round requested')
    row = _task_row(ctx, root, 'TASK-D5')
    _require(row['status'] == 'BLOCKED', f'expected BLOCKED after the cap, got {row["status"]}')
    _require(row['retries'] >= 3, f'retry counter is {row["retries"]}, expected at least 3')
    note = _task_row(ctx, root, 'TASK-D5', 'last_note')['last_note']
    _require('Retry cap reached' in note, f'the block note does not explain the cap: {note!r}')
    return [f'retries={row["retries"]}' , 'fourth round -> BLOCKED',
            f'note: {note}']


def scenario_d6(ctx):
    """BLOCKING / NEEDS_HUMAN_DECISION in the audit forbid a closeout claim."""
    header = '| 检查项 | verdict | 依据 |\n|---|---|---|\n'
    clean = header + ('| functional completeness | PASS | task 1 evidence, head aaaa |\n'
                      '| cross-module invariants | NON_BLOCKING_HARDENING | tracked as hardening |\n'
                      '| residual items | NOT_APPLICABLE | N/A: no legacy data in this stage |\n')
    _expect_clean(ctx.vk.audit_conclusion_errors('## 阶段审计结论\n\n' + clean),
                  'clean audit closeout')

    blocking = clean + '| permissions and security | BLOCKING | probe missing |\n'
    finding = _expect_finding(ctx.vk.audit_conclusion_errors('## 阶段审计结论\n\n' + blocking),
                              'BLOCKING', 'blocking audit row')
    _require('不得标记为完成' in finding or 'not be claimed complete' in finding,
             f'the BLOCKING finding does not forbid the closeout: {finding}')

    human = clean + '| legacy data migration | NEEDS_HUMAN_DECISION | owner has not decided |\n'
    human_finding = _expect_finding(ctx.vk.audit_conclusion_errors('## 阶段审计结论\n\n' + human),
                                    'NEEDS_HUMAN_DECISION', 'human-decision audit row')
    return [f'clean audit: 0 findings (PASS / NON_BLOCKING_HARDENING / NOT_APPLICABLE)',
            f'gate fired: {finding}', f'gate fired: {human_finding}']


def scenario_d7(ctx):
    """An executor's unbacked 'done' claim cannot reach APPROVED or VERIFIED."""
    fields = _canonical(ctx)[0]
    text = _packet(ctx, [('x', 'AC-1', 'the change is verified')], [])
    findings = _packet_errors(ctx, text)
    empty = _expect_finding(findings, 'evidence matrix has no evidence items', 'empty matrix')
    no_evidence = _expect_finding(findings, 'AC-1 has no evidence item', 'unbacked AC')

    root = _project_root(ctx)
    _add(ctx, root, 'TASK-D7', ['src/d7.py'])
    verify = _expect_refused(lambda: _status(ctx, root, 'TASK-D7', 'VERIFIED'),
                             'illegal transition PLANNED -> VERIFIED', 'self-verification')
    _require(_count(ctx, root, 'SELECT COUNT(*) FROM locks WHERE task_id=?', ('TASK-D7',)) == 0,
             'a refused VERIFIED left locks behind')
    _require(fields, 'evidence contract is empty')
    return [f'gate fired: {empty}', f'gate fired: {no_evidence}', f'state machine: {verify}']


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
SCENARIOS = (
    Scenario('A1', 'A', 'positive', 'legal packet and legal approval cycle',
             'a fresh local project with an explicit edition; one legal packet fixture',
             'none (positive control)',
             'G1/G5: 0 findings; PLANNED -> VERIFIED with head-bound approval',
             'packet findings, task status, approved_sha, remaining locks',
             'temporary project root removed with the scenario sandbox', scenario_a1),
    Scenario('A2', 'A', 'negative', 'authorization revoked but the AC stays met',
             'one AC with a FAIL evidence row for the revoked grant',
             'the task keeps AC-2 checked although its evidence is FAIL',
             'G1: an AC marked as met with FAIL evidence is rejected',
             'validator finding text', 'no state written; sandbox removed', scenario_a2),
    Scenario('A3', 'A', 'negative', 'audit context missing (no evidence item)',
             'two ACs, only one evidence row',
             'AC-2 is checked without any evidence mapping',
             'G1: every AC needs at least one evidence item',
             'validator finding text', 'sandbox removed', scenario_a3),
    Scenario('A4', 'A', 'negative', 'empty acceptance criterion',
             'AC-1 declared with an empty statement',
             'a bare "- [ ] AC-1:" line is treated as an acceptance criterion',
             'G1: an AC without a checkable statement is rejected',
             'validator finding text', 'sandbox removed', scenario_a4),
    Scenario('A5', 'A', 'negative', 'NOT_RUN disguised as PASS',
             'one PASS row whose actual text says the suite did not run',
             'a not-executed check is recorded as PASS',
             'G1: PASS rows that report not-run/blocked evidence are rejected',
             'validator finding text', 'sandbox removed', scenario_a5),
    Scenario('A6', 'A', 'negative', 'duplicate write and concurrent state change',
             'two tasks sharing one allowed path, one already dispatched',
             'a second dispatch of the same task and a concurrent claim on the path',
             'path lock + state machine: both calls are refused, no lock is left behind',
             'refusal messages, lock counts for the refused task', 'sandbox removed', scenario_a6),
    Scenario('A7', 'A', 'negative', 'executor self-approval',
             'a dispatched task with no review states visited',
             'the executor sets APPROVED / VERIFIED directly',
             'G6: illegal transitions are refused and the task does not move',
             'refusal messages, status and approved_sha after the attempt',
             'sandbox removed', scenario_a7),
    Scenario('B1', 'B', 'positive', 'idempotent migration with version isolation',
             'three synthetic legacy records at version 2014',
             'none (positive control)',
             'migration: count, version, ids and completion marker all consistent after a rerun',
             'artifact digest before/after rerun, verification findings',
             'synthetic artifact removed with the sandbox', scenario_b1),
    Scenario('B2', 'B', 'negative', 'migration interrupted halfway',
             'a legacy artifact plus a backup copy',
             'only one of three records is written and the completion marker is absent',
             'migration: partial writes are reported, recovery from the backup verifies clean',
             'verification findings before/after recovery', 'sandbox removed', scenario_b2),
    Scenario('B3', 'B', 'negative', 'two versions mixed in one target set',
             'a migrated set where one row still carries version 2014',
             'version isolation is broken while the migration claims completion',
             'migration: a mixed-version row is reported as a version isolation break',
             'verification finding text', 'sandbox removed', scenario_b3),
    Scenario('B4', 'B', 'negative', 'migration completed claim without an artifact',
             'a structurally valid packet claiming the upgrade is done; no artifact on disk',
             'the claim is the only evidence; the artifact does not exist',
             'G1 + artifact check: the claim is well formed but contradicted by the artifact',
             'packet findings (none) and the artifact-check finding',
             'sandbox removed', scenario_b4),
    Scenario('C1', 'C', 'positive', 'wired rule with a complete event chain',
             'a three-step synthetic turn with ownership, rule and commit barrier wired',
             'none (positive control)',
             'cross-module: rule wired, ownership honoured, commit barrier respected',
             'event list and invariant findings', 'in-memory only', scenario_c1),
    Scenario('C2', 'C', 'negative', 'frozen rule never called',
             'the same turn with the action_resolved rule unwired',
             'the frozen rule is dropped from the call path',
             'cross-module: the missing event is reported as an unwired rule',
             'event list and finding text', 'in-memory only', scenario_c2),
    Scenario('C3', 'C', 'negative', 'ownership check missing',
             'a turn where player-2 acts on a unit owned by player-1',
             'the ownership guard is disabled',
             'cross-module: an action resolved by a non-owner is reported',
             'finding text', 'in-memory only', scenario_c3),
    Scenario('C4', 'C', 'negative', 'event barrier missing',
             'a turn whose state change is emitted before the commit',
             'the commit barrier is bypassed',
             'cross-module: the ordering violation is reported',
             'event list and finding text', 'in-memory only', scenario_c4),
    Scenario('C5', 'C', 'negative', 'non-assertion exception in the test runner',
             'a synthetic unittest module with one passing, one crashing and one later test',
             'test_second_raises raises ZeroDivisionError instead of failing an assertion',
             'runner: the crash is recorded as an error, the traceback is kept, later tests run',
             'testsRun / errors / failures counts, preserved traceback, execution order',
             'in-memory only', scenario_c5),
    Scenario('C6', 'C', 'positive', 'guarded shared state with an exact recovery',
             'a synthetic data tree, a shared manifest and a lock file in one sandbox',
             'none (positive control)',
             'shared state: every call site is guarded, the rollback matches the baseline tree, '
             'the lock is released and the directory scan reports no finding',
             'manifest counters, tree digest vs baseline, lock state, scan report',
             'synthetic sandbox removed with the scenario', scenario_c6),
    Scenario('C7', 'C', 'negative', 'one shared-state call site left unguarded',
             'a shared manifest with two writers, the second one interleaved inside the '
             'first read-modify-write window',
             'the autosave call site runs the cycle without taking the lock',
             'shared state: the inventory names the unguarded call site and the final counter '
             'shows a lost update; the guarded rerun keeps both',
             'call-site inventory, final count and writer list before/after the fix',
             'synthetic sandbox removed with the scenario', scenario_c7),
    Scenario('C8', 'C', 'negative', 'rollback leaves files the backup never knew',
             'a synthetic data tree with a snapshot taken before the change',
             'the rollback restores the remembered files and keeps the newly created ones',
             'recovery: the residue is reported and the tree still differs from the baseline; '
             'the exact restore then matches it',
             'residue list, tree comparison before/after the exact rollback',
             'synthetic sandbox removed with the scenario', scenario_c8),
    Scenario('C9', 'C', 'negative', 'business rollback deletes the lock file',
             'a data tree plus a lock file created after the whole-root snapshot',
             'the rollback restores the whole root, removing the live lock',
             'lock lifecycle: the second writer acquires the orphaned lock; the data-only '
             'rollback keeps the lock and still refuses the second writer',
             'lock presence, second-writer acquisition, LOCK_HELD refusal, tree digest',
             'synthetic sandbox removed with the scenario', scenario_c9),
    Scenario('C10', 'C', 'negative', 'partial commit reported as a complete rollback',
             'a three-stage multi-file commit that fails at the second stage',
             'the report claims rollback COMPLETE although stage 1 is still on disk',
             'staged failure: the honest report names the failed stage, the completed stage, '
             'the side effects and the backup, and the false claim is contradicted by the tree',
             'stage report fields, remaining files in the data tree',
             'synthetic sandbox removed with the scenario', scenario_c10),
    Scenario('C11', 'C', 'negative', 'directory read error swallowed',
             'a directory holding two readable files and one entry that cannot be read as a file',
             'the scan skips the unreadable entry and still reports success',
             'error semantics: the success report is contradicted by processed != total; the '
             'corrected scan reports FAILED and names the entry',
             'scan report before/after the fix, skipped and error lists',
             'synthetic sandbox removed with the scenario', scenario_c11),
    Scenario('C12', 'C', 'positive', 'clean architecture contract with honest coverage',
             'a synthetic tree with domain, application, adapter and two transport entry points',
             'none (positive control)',
             'architecture contract: ENFORCE, no error, scope reported, both transports agree, '
             'mock evidence never labelled real, capability claims bound to a probe',
             'JSON report (status, counts, examined modules, invariant coverage), shared '
             'contract test result, terminal-state matrix, capability findings',
             'synthetic sandbox removed with the scenario', scenario_c12),
    Scenario('C13', 'C', 'negative', 'core module imports an adapter private symbol',
             'the application service importing the adapter runtime session module',
             'the adapter private path leaks into the core through an import',
             'PRIVATE_ACCESS: blocking under ENFORCE, located at rule / module / file / line, '
             'and the bound invariant follows the rule',
             'report blocking flag, PRIVATE_ACCESS finding, invariant coverage',
             'synthetic sandbox removed with the scenario', scenario_c13),
    Scenario('C14', 'C', 'negative', 'two transports implement forked business rules',
             'one transport delegating to the application service, one re-implementing the rule',
             'inline duplication that no import edge reveals, plus the same fork as a direct '
             'domain import',
             'FORBIDDEN_EDGE blocks the structural fork; the shared contract test catches the '
             'inline one; the invariant declared CONTRACT_TEST stays UNKNOWN',
             'static blocking flag per variant, behaviour differences, invariant coverage',
             'synthetic sandbox removed with the scenario', scenario_c14),
    Scenario('C15', 'C', 'negative', 'mock adapter result reported as real verification',
             'a passing shared adapter contract suite executed against a mock implementation',
             'the run is labelled REAL_RUNTIME although the evidence kind is MOCK',
             'evidence labelling: the over-claim is rejected and the mock run stays UNKNOWN '
             'for real-runtime verification',
             'claim findings, verification status per evidence kind',
             'synthetic sandbox removed with the scenario', scenario_c15),
    Scenario('C16', 'C', 'negative', 'cancel, timeout, failure and unknown collapsed',
             'four non-success dispatch terminal states recorded through one generic error',
             'one error code covers failure, cancellation, timeout and "unknown", and unknown '
             'is rewritten as a failure',
             'terminal-state contract: collapsed codes are reported, "unknown" never becomes '
             'success, and the distinct variants keep one code per state',
             'terminal findings, code sets before/after the fix',
             'synthetic sandbox removed with the scenario', scenario_c16),
    Scenario('C17', 'C', 'negative', 'capability marked PASS without evidence',
             'capability records for execution isolation and cancellation',
             'PASS with no probe, with "startup succeeded", with a wildcard scope, or with a '
             'probe that covers a different capability',
             'capability claim gate: every over-claim is rejected, an honest UNKNOWN claim is '
             'accepted and never upgraded',
             'capability findings per record',
             'synthetic sandbox removed with the scenario', scenario_c17),
    Scenario('C18', 'C', 'positive', 'unconfigured project is not judged by inferred rules',
             'the same violating tree without any Architecture Contract',
             'none (positive control): nothing may be guessed from the code alone',
             'contract optionality: OFF / diagnostic only, exit 0, no ERROR or WARNING, no '
             'invariant and no examined module claimed; declaring the contract then blocks',
             'report mode, status, counts, inventory, and the contrast after declaring',
             'synthetic sandbox removed with the scenario', scenario_c18),
    Scenario('D1', 'D', 'positive', 'legal edition with a declared resource',
             'a local project with resource_lease_ttl configured',
             'none (positive control)',
             'edition + resource lock: legal dispatch acquires, VERIFIED releases',
             'edition value, lock rows before/after closeout', 'sandbox removed', scenario_d1),
    Scenario('D2', 'D', 'negative', 'illegal, missing or duplicated edition',
             'four project roots with a missing file, a missing key, an illegal value and a duplicate key',
             'each root declares an unusable edition; one declares github',
             'edition: every case fails closed and names the file to fix; github refuses local scheduling',
             'four refusal messages', 'sandbox removed', scenario_d2),
    Scenario('D3', 'D', 'negative', 'conflicting exclusive resource lock',
             'two tasks with disjoint paths declaring the same exclusive resource',
             'the second task requests the resource the first one holds',
             'resource lock: MODE_CONFLICT denial, no half lock, audit event kept',
             'refusal message, lock counts, denial event count, task status',
             'sandbox removed', scenario_d3),
    Scenario('D4', 'D', 'negative', 'new head invalidates the old approval',
             'a task approved at head aaaa, then a workspace update to another head',
             'the approval is reused for a head that was never reviewed',
             'G3/G4: approval is cleared, merge and in-place re-approval are refused',
             'status, approved_sha, refusal messages', 'sandbox removed', scenario_d4),
    Scenario('D5', 'D', 'negative', 'review-fix rounds beyond the cap',
             'a task that went through three review-fix rounds',
             'a fourth round is requested instead of blocking',
             'state machine: the fourth round becomes BLOCKED with the cap in the note',
             'status, retry counter, block note', 'sandbox removed', scenario_d5),
    Scenario('D6', 'D', 'negative', 'audit closeout with a blocking verdict',
             'a filled milestone-audit conclusion table',
             'one row is BLOCKING and one is NEEDS_HUMAN_DECISION',
             'milestone audit: a clean table passes; blocking verdicts forbid the closeout claim',
             'findings for the clean and the two blocking tables', 'in-memory only', scenario_d6),
    Scenario('D7', 'D', 'negative', 'unbacked result claim',
             'a packet whose AC is checked and whose evidence matrix is empty',
             'the executor claims completion without any evidence item',
             'G1/G6: empty matrix, unbacked AC and direct VERIFIED are all refused',
             'validator findings, refusal message, lock count', 'sandbox removed', scenario_d7),
)


def scenario_ids():
    return [scenario.id for scenario in SCENARIOS]


def select_scenarios(only=None):
    if not only:
        return list(SCENARIOS)
    wanted = {item.strip() for item in only if item.strip()}
    known = set(scenario_ids())
    unknown = sorted(wanted - known)
    if unknown:
        raise ToolError(f'unknown scenario id(s): {", ".join(unknown)}; '
                        f'known ids: {", ".join(scenario_ids())}')
    return [scenario for scenario in SCENARIOS if scenario.id in wanted]


# --------------------------------------------------------------------------- #
# Execution and reporting
# --------------------------------------------------------------------------- #
def _redact(text, sandbox):
    """Keep the report free of this machine's temporary paths."""
    text = '' if text is None else str(text)
    for raw in {str(sandbox), str(sandbox).replace('\\', '/')}:
        text = text.replace(raw, '<sandbox>')
    return text


def run_scenarios(scenarios, workdir, vk=None, orch=None, emit=None):
    """Run every scenario; a failure or crash never stops the remaining ones."""
    results = []
    for index, scenario in enumerate(scenarios, 1):
        sandbox = Path(workdir) / f'{index:02d}-{scenario.id}'
        sandbox.mkdir(parents=True, exist_ok=True)
        context = Context(vk=vk, orch=orch, sandbox=sandbox)
        try:
            evidence = scenario.fn(context) or []
            if not isinstance(evidence, list):
                evidence = [str(evidence)]
            result = Result(scenario, 'PASS', [_redact(item, sandbox) for item in evidence], {})
        except ScenarioFailed as exc:
            result = Result(scenario, 'FAIL', [], {
                'type': type(exc).__name__,
                'message': _redact(str(exc), sandbox),
                'traceback': _redact(traceback.format_exc(), sandbox),
            })
        except Exception as exc:  # noqa: BLE001 - recorded, never re-raised
            result = Result(scenario, 'ERROR', [], {
                'type': type(exc).__name__,
                'message': _redact(str(exc), sandbox),
                'traceback': _redact(traceback.format_exc(), sandbox),
            })
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        results.append(result)
        if emit is not None:
            emit(result)
    return results


def build_report(results, started_at=None):
    counts = {'scenarios': len(results), 'passed': 0, 'failed': 0, 'errors': 0,
              'positive': 0, 'negative': 0, 'positive_passed': 0, 'negative_passed': 0}
    for result in results:
        scenario = result.scenario
        counts['positive' if scenario.kind == 'positive' else 'negative'] += 1
        if result.status == 'PASS':
            counts['passed'] += 1
            counts[f'{"positive" if scenario.kind == "positive" else "negative"}_passed'] += 1
        elif result.status == 'FAIL':
            counts['failed'] += 1
        else:
            counts['errors'] += 1
    groups = {}
    for key, label in GROUPS.items():
        in_group = [r for r in results if r.scenario.group == key]
        groups[key] = {'label': label, 'scenarios': len(in_group),
                       'passed': sum(1 for r in in_group if r.status == 'PASS')}
    return {
        'schema': REPORT_SCHEMA,
        'generated_at': started_at or datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'python': platform.python_version(),
        'platform': platform.platform(),
        'scenario_doc': SCENARIO_DOC,
        'totals': counts,
        'groups': groups,
        'scenarios': [{
            'id': r.scenario.id,
            'group': r.scenario.group,
            'kind': r.scenario.kind,
            'title': r.scenario.title,
            'status': r.status,
            'precondition': r.scenario.precondition,
            'injected_defect': r.scenario.defect,
            'expected_gate': r.scenario.gate,
            'evidence_declared': r.scenario.evidence,
            'cleanup': r.scenario.cleanup,
            'evidence': list(r.evidence),
            'error': r.error or None,
        } for r in results],
    }


def format_human(report):
    totals = report['totals']
    lines = ['Synthetic delivery regression scenarios',
             f'  {totals["scenarios"]} scenarios: {totals["positive"]} positive control(s), '
             f'{totals["negative"]} injected-defect scenario(s)']
    for key in GROUPS:
        group = report['groups'][key]
        lines.append(f'  {key} {group["label"]}: {group["passed"]}/{group["scenarios"]} passed')
    lines.append('')
    for item in report['scenarios']:
        marker = {'PASS': 'PASS ', 'FAIL': 'FAIL ', 'ERROR': 'ERROR'}[item['status']]
        lines.append(f'{marker} {item["id"]}  {item["title"]}')
        if item['status'] == 'PASS':
            for evidence in item['evidence']:
                lines.append(f'       - {evidence}')
        else:
            lines.append(f'       gate: {item["expected_gate"]}')
            lines.append(f'       {item["error"]["type"]}: {item["error"]["message"]}')
    lines.append('')
    lines.append(f'Summary: {totals["passed"]} passed, {totals["failed"]} failed, '
                 f'{totals["errors"]} errored of {totals["scenarios"]}')
    lines.append('Exit code: ' + ('0 (all scenarios passed)'
                                  if totals['passed'] == totals['scenarios']
                                  else '1 (at least one scenario failed or errored)'))
    return '\n'.join(lines)


def _exit_code(results):
    return EXIT_PASS if all(result.status == 'PASS' for result in results) else EXIT_SCENARIO_FAILURES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true',
                        help='print the machine-readable report instead of the human summary')
    parser.add_argument('--output', metavar='PATH',
                        help='also write the JSON report to PATH (never written into the kit)')
    parser.add_argument('--only', action='append', metavar='ID',
                        help='run only the given scenario id (repeatable)')
    parser.add_argument('--list', action='store_true', help='list scenario ids and exit')
    args = parser.parse_args(argv)

    if args.list:
        for scenario in SCENARIOS:
            print(f'{scenario.id}\t{scenario.group}\t{scenario.kind}\t{scenario.title}')
        return EXIT_PASS

    try:
        selected = select_scenarios(args.only)
        vk = _load_module('agentorch_validate_kit', SCRIPTS / 'validate_kit.py')
        orch = _load_module('agentorch_orchestrator', SCRIPTS / 'orchestrator.py')
    except ToolError as exc:
        print(f'RUNNER ERROR: {exc}', file=sys.stderr)
        return EXIT_TOOL_ERROR

    workdir = tempfile.TemporaryDirectory(prefix='agentorch-delivery-scenarios-')
    try:
        results = run_scenarios(selected, workdir.name, vk=vk, orch=orch)
    finally:
        workdir.cleanup()

    report = build_report(results)
    if args.output:
        try:
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                         encoding='utf-8')
        except OSError as exc:
            print(f'RUNNER ERROR: cannot write --output {args.output}: {exc}', file=sys.stderr)
            return EXIT_TOOL_ERROR

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_human(report))
    return _exit_code(results)


if __name__ == '__main__':
    sys.exit(main())
