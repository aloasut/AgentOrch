#!/usr/bin/env python3
"""Synthetic delivery regression scenarios for the Agent-Orchestration kit.

This runner answers one question the documents cannot answer by themselves:
does the kit *stop* the failures it describes? Four groups are covered, each
taken from a typical failure mode rather than from a product's private data:

  A  governance / authorization   (evidence gates, revocation, duplicate writes)
  B  migration / versioning       (rerun, partial write, version isolation)
  C  cross-module closeout        (unwired rule, ownership, event barrier, crash)
  D  orchestration base           (edition, resource lock, stale SHA, retries, audit)

Every scenario declares its precondition, the defect it injects, the gate that
must fire and the evidence it leaves behind; `docs/testing/DELIVERY-REGRESSION-SCENARIOS.md`
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
SCENARIO_DOC = 'docs/testing/DELIVERY-REGRESSION-SCENARIOS.md'
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
    'C': 'cross-module closeout',
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
    (root / 'ORCHESTRATION-PROJECT.md').write_text(
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
        (root / 'ORCHESTRATION-PROJECT.md').write_text(body, encoding='utf-8')
        message = _expect_refused(lambda root=root: ctx.orch.read_project_edition(root),
                                  'ORCHESTRATION-PROJECT.md', label)
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
