#!/usr/bin/env python3
"""Project-internal role performance feedback and explainable calibration (#123, S4).

Design contract: ``docs/design/agent-role-discovery-and-model-selection.md``
§8–§9. External leaderboards are a prior; what a role actually did in *this*
scope is supplementary evidence, and the two never impersonate each other.

The module deliberately has a narrow surface:

* it writes only to the current scope's ``observed-performance.md`` through the
  S1 :class:`scripts.agent_selection.local_store.LocalStore`. There is no second
  store, no JSON / SQLite file and no cross-scope read: a report always carries
  the scope id of the store it was built from, and an outcome that names another
  scope is refused before anything is written.
* an entry only counts when it carries at least one *sufficient* evidence
  reference (a task record, a review conclusion, acceptance evidence, a
  regression defect, a master review or a comparison baseline). Chat memory, an
  agent's self-assessment, a merge event or a green CI run are recorded as
  insufficient: they can accompany an entry but can never be its whole basis.
* every metric reports its sample size, its window, its task category, its
  missing count and its coverage. Rates are pooled over the entries that really
  have the value; a missing value is ``UNKNOWN``, never ``0``.
* cohorts are keyed by role + task category + exact model / runtime identity.
  Different task categories, benchmark data, price currencies or price units are
  never added together, and a cohort whose identity differs from the identity
  currently in use is ``IDENTITY_CHANGED`` instead of "carried forward".
* output is advisory. :class:`FeedbackReport` is structurally
  ``applied_automatically=False`` / ``changes_configuration=False``, keeps no
  permanent "best role", and refuses a ranking while the samples, the identity
  or the comparison basis are insufficient.

Standard library only. No network, no third-party dependency, and no real
``.local`` directory: tests always use a temporary project root.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import local_store
from .local_store import StoreError
from .roles import (
    PROJECT_MIN_SAMPLES,
    ROLE_EXECUTION,
    ROLE_MASTER,
    ROLE_REVIEWER,
)

__all__ = [
    'FEEDBACK_DOCUMENT',
    'SCHEMA_VERSION',
    'UNKNOWN',
    'FIRST_ACCEPTANCE_RESULTS',
    'SEVERITIES',
    'MASTER_SIGNALS',
    'EVIDENCE_KINDS',
    'INSUFFICIENT_EVIDENCE_KINDS',
    'METRIC_STATUSES',
    'METRIC_DIRECTIONS',
    'METRICS_BY_ROLE',
    'MASTER_SIGNAL_FOR_METRIC',
    'FeedbackError',
    'FeedbackScopeError',
    'FeedbackEvidenceError',
    'FeedbackWriteError',
    'ModelIdentity',
    'EvidenceRef',
    'Cost',
    'ExecutionOutcome',
    'ReviewerOutcome',
    'MasterOutcome',
    'FeedbackPolicy',
    'Metric',
    'Cohort',
    'Comparison',
    'ComparisonRow',
    'Recommendation',
    'LoadResult',
    'FeedbackReport',
    'record_outcome',
    'load_outcomes',
    'build_report',
]

FEEDBACK_DOCUMENT = 'observed-performance.md'
SCHEMA_VERSION = 's4-feedback-1'
UNKNOWN = 'UNKNOWN'

FIRST_ACCEPTANCE_RESULTS = ('PASS', 'FAIL', UNKNOWN)
SEVERITIES = ('HIGH', 'MEDIUM', 'LOW', 'NONE', UNKNOWN)
MASTER_SIGNALS = ('planning_omissions', 'task_split_rework',
                  'decision_corrections', 'requirement_deviations')

# A sufficient evidence reference points at a task-carrier fact someone else can
# open again. The insufficient set is not "forbidden": it is "never the whole
# basis" (design §9: merge success and CI green are not review quality).
EVIDENCE_KINDS = ('task_record', 'review_conclusion', 'acceptance_evidence',
                  'regression_defect', 'master_review', 'comparison_baseline')
INSUFFICIENT_EVIDENCE_KINDS = ('chat_memory', 'self_assessment',
                               'merge_record', 'ci_result')

METRIC_STATUSES = ('OK', 'NO_DATA', 'INSUFFICIENT_SAMPLE', 'NO_COMPARATOR',
                   'IDENTITY_CHANGED', 'NOT_COMPARABLE', 'STALE')

# Which direction is "better". Only rates and means are compared, never a
# composite score; a role is never declared permanently best.
METRIC_DIRECTIONS = {
    'first_acceptance_pass_rate': 'higher',
    'mean_rework_rounds': 'lower',
    'post_merge_regression_defect_rate': 'lower',
    'mean_delivery_seconds': 'lower',
    'mean_cost': 'lower',
    'confirmed_issue_rate': 'higher',
    'false_positive_rate': 'lower',
    'mean_missed_issues_per_review': 'lower',
    'regression_blocked_rate': 'higher',
    'high_severity_share': 'lower',
    'mean_planning_omissions': 'lower',
    'mean_task_split_rework': 'lower',
    'mean_decision_corrections': 'lower',
    'mean_requirement_deviations': 'lower',
}

METRICS_BY_ROLE = {
    ROLE_EXECUTION: ('first_acceptance_pass_rate', 'mean_rework_rounds',
                     'post_merge_regression_defect_rate',
                     'mean_delivery_seconds', 'mean_cost'),
    ROLE_REVIEWER: ('confirmed_issue_rate', 'false_positive_rate',
                    'mean_missed_issues_per_review', 'regression_blocked_rate',
                    'high_severity_share'),
    ROLE_MASTER: ('mean_planning_omissions', 'mean_task_split_rework',
                  'mean_decision_corrections',
                  'mean_requirement_deviations'),
}

# One Master plan signal maps to exactly one reported metric; keeping the two
# names apart avoids inventing a prefix rule at read time.
MASTER_SIGNAL_FOR_METRIC = {
    'mean_planning_omissions': 'planning_omissions',
    'mean_task_split_rework': 'task_split_rework',
    'mean_decision_corrections': 'decision_corrections',
    'mean_requirement_deviations': 'requirement_deviations',
}

_CATEGORY_RE = re.compile(r'[a-z0-9][a-z0-9._-]{0,31}')
_TOKEN_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,63}')
_REFERENCE_LIMIT = 200


class FeedbackError(ValueError):
    """A feedback outcome violates the S4 contract."""


class FeedbackScopeError(FeedbackError):
    """The outcome names a scope other than the store's own scope."""


class FeedbackEvidenceError(FeedbackError):
    """The outcome has no sufficient evidence, so it must not be recorded."""


class FeedbackWriteError(FeedbackError):
    """The record was not written; the caller must not claim it was."""


# --- validation helpers ------------------------------------------------------
def _timestamp(value, label):
    if not isinstance(value, str):
        raise FeedbackError(f'{label} must be a UTC timestamp string')
    try:
        return local_store.utc_timestamp(value)
    except ValueError as exc:
        raise FeedbackError(f'{label} must look like 2030-01-01T00:00:00Z: {exc}') from exc


def _parse_utc(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def _category(value):
    if not isinstance(value, str) or not _CATEGORY_RE.fullmatch(value):
        raise FeedbackError(
            'task_category must be a lowercase slug such as "code-change" or '
            f'"test-infra", got {value!r}')
    return value


def _token(value, label):
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise FeedbackError(
            f'{label} must be a short single token without spaces, pipes or '
            f'semicolons, got {value!r}')
    return value


def _count(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FeedbackError(f'{label} must be a non-negative integer or None, got {value!r}')
    return value


def _optional_bool(value, label):
    if value is None or isinstance(value, bool):
        return value
    raise FeedbackError(f'{label} must be True, False or None, got {value!r}')


def _evidence_tuple(evidence):
    if not evidence:
        raise FeedbackEvidenceError(
            'an outcome needs at least one evidence reference; a memory, a '
            'self-assessment, a merge event or a green CI run is not quality '
            'evidence on its own')
    for item in evidence:
        if not isinstance(item, EvidenceRef):
            raise FeedbackError(f'evidence must be EvidenceRef items, got {item!r}')
    if not any(item.sufficient for item in evidence):
        kinds = ', '.join(sorted({item.kind for item in evidence}))
        raise FeedbackEvidenceError(
            f'the supplied evidence ({kinds}) is not sufficient: at least one '
            'task record, review conclusion, acceptance evidence, regression '
            'defect, master review or comparison baseline is required')
    return tuple(evidence)


# --- value objects -----------------------------------------------------------
@dataclass(frozen=True)
class ModelIdentity:
    """The exact model / runtime identity an observation belongs to.

    A new model id or a new runtime version is a new identity: the records of
    the old one are not carried forward (design §8.4, §9).
    """

    model_id: str = UNKNOWN
    runtime_id: str = UNKNOWN
    runtime_version: str = UNKNOWN

    def __post_init__(self):
        for name in ('model_id', 'runtime_id', 'runtime_version'):
            object.__setattr__(self, name, _token(getattr(self, name), name))

    @property
    def key(self):
        return f'{self.model_id}|{self.runtime_id}|{self.runtime_version}'

    @property
    def known(self):
        return UNKNOWN not in (self.model_id, self.runtime_id, self.runtime_version)

    def as_dict(self):
        return {'model_id': self.model_id, 'runtime_id': self.runtime_id,
                'runtime_version': self.runtime_version, 'known': self.known}


@dataclass(frozen=True)
class EvidenceRef:
    """One locator for a fact someone else can re-open."""

    kind: str
    ref: str
    observed_at: str = ''

    def __post_init__(self):
        if self.kind not in EVIDENCE_KINDS + INSUFFICIENT_EVIDENCE_KINDS:
            raise FeedbackError(
                f'unknown evidence kind {self.kind!r}; expected one of '
                f'{EVIDENCE_KINDS + INSUFFICIENT_EVIDENCE_KINDS}')
        if not isinstance(self.ref, str) or not self.ref.strip():
            raise FeedbackError('an evidence reference needs a locator')
        if '|' in self.ref or ';' in self.ref or len(self.ref) > _REFERENCE_LIMIT:
            raise FeedbackError(
                'an evidence locator must be single-line, <= 200 characters and '
                'must not contain "|" or ";"')
        object.__setattr__(self, 'observed_at',
                           _timestamp(self.observed_at, 'evidence observed_at'))

    @property
    def sufficient(self):
        return self.kind in EVIDENCE_KINDS

    def encode(self):
        return f'{self.kind}|{self.ref}|{self.observed_at}'

    @classmethod
    def decode(cls, value):
        parts = str(value).split('|')
        if len(parts) != 3:
            raise FeedbackError(f'unreadable evidence reference {value!r}')
        return cls(kind=parts[0], ref=parts[1], observed_at=parts[2])

    def as_dict(self):
        return {'kind': self.kind, 'ref': self.ref,
                'observed_at': self.observed_at, 'sufficient': self.sufficient}


@dataclass(frozen=True)
class Cost:
    """A real, collected cost with its currency and price unit.

    ``currency`` + ``unit`` is part of the cohort key: two different price units
    are never averaged into one number.
    """

    amount: float
    currency: str = 'USD'
    unit: str = 'per_task'

    def __post_init__(self):
        if isinstance(self.amount, bool) or not isinstance(self.amount, (int, float)) \
                or self.amount < 0:
            raise FeedbackError(f'cost amount must be a non-negative number, got {self.amount!r}')
        currency = self.currency.upper() if isinstance(self.currency, str) else ''
        if not re.fullmatch(r'[A-Z]{3}', currency):
            raise FeedbackError(f'cost currency must be a 3-letter code, got {self.currency!r}')
        object.__setattr__(self, 'currency', currency)
        object.__setattr__(self, 'unit', _category(self.unit))

    def as_dict(self):
        return {'amount': self.amount, 'currency': self.currency, 'unit': self.unit}


def _validate_outcome(category, identity, observed_at, evidence):
    _category(category)
    if not isinstance(identity, ModelIdentity):
        raise FeedbackError('identity must be a ModelIdentity')
    for item in evidence:
        if not isinstance(item, EvidenceRef):
            raise FeedbackError(f'evidence must be EvidenceRef items, got {item!r}')
    return _timestamp(observed_at, 'observed_at')


@dataclass(frozen=True)
class ExecutionOutcome:
    """What one Execution task actually produced (design §9, first bullet)."""

    task_id: str
    category: str
    identity: ModelIdentity
    observed_at: str
    evidence: tuple = ()
    first_acceptance: str = UNKNOWN
    rework_rounds: int | None = None
    post_merge_regression_defects: int | None = None
    duration_seconds: int | None = None
    cost: Cost | None = None
    scope_id: str = ''

    role = ROLE_EXECUTION

    def __post_init__(self):
        _token(self.task_id, 'task_id')
        object.__setattr__(self, 'observed_at', _validate_outcome(
            self.category, self.identity, self.observed_at, self.evidence))
        object.__setattr__(self, 'evidence', _evidence_tuple(self.evidence))
        if self.first_acceptance not in FIRST_ACCEPTANCE_RESULTS:
            raise FeedbackError(
                f'first_acceptance must be one of {FIRST_ACCEPTANCE_RESULTS}')
        for name in ('rework_rounds', 'post_merge_regression_defects',
                     'duration_seconds'):
            object.__setattr__(self, name, _count(getattr(self, name), name))
        if self.cost is not None and not isinstance(self.cost, Cost):
            raise FeedbackError('cost must be a Cost or None')

    @property
    def summary(self):
        return (f'{self.role} {self.category} {self.task_id} '
                f'first_acceptance={self.first_acceptance} '
                f'rework={self.rework_rounds if self.rework_rounds is not None else UNKNOWN}')

    def as_details(self):
        details = {
            'role': self.role,
            'schema': SCHEMA_VERSION,
            'task_id': self.task_id,
            'task_category': self.category,
            'model_id': self.identity.model_id,
            'runtime_id': self.identity.runtime_id,
            'runtime_version': self.identity.runtime_version,
            'observed_at': self.observed_at,
            'first_acceptance': self.first_acceptance,
            'rework_rounds': _render_optional(self.rework_rounds),
            'regression_defects': _render_optional(self.post_merge_regression_defects),
            'duration_seconds': _render_optional(self.duration_seconds),
            'cost_amount': (str(self.cost.amount) if self.cost is not None else UNKNOWN),
            'cost_currency': (self.cost.currency if self.cost is not None else UNKNOWN),
            'cost_unit': (self.cost.unit if self.cost is not None else UNKNOWN),
        }
        details.update(_render_evidence(self.evidence))
        return details


@dataclass(frozen=True)
class ReviewerOutcome:
    """What one review actually found and what it wrongly claimed (design §9)."""

    review_id: str
    category: str
    identity: ModelIdentity
    observed_at: str
    evidence: tuple = ()
    confirmed_issues: int | None = None
    false_positives: int | None = None
    severity: str = UNKNOWN
    missed_issues: int | None = None
    baseline: EvidenceRef | None = None
    blocked_regression: bool | None = None
    scope_id: str = ''

    role = ROLE_REVIEWER

    def __post_init__(self):
        _token(self.review_id, 'review_id')
        object.__setattr__(self, 'observed_at', _validate_outcome(
            self.category, self.identity, self.observed_at, self.evidence))
        object.__setattr__(self, 'evidence', _evidence_tuple(self.evidence))
        for name in ('confirmed_issues', 'false_positives', 'missed_issues'):
            object.__setattr__(self, name, _count(getattr(self, name), name))
        if self.severity not in SEVERITIES:
            raise FeedbackError(f'severity must be one of {SEVERITIES}')
        object.__setattr__(self, 'blocked_regression',
                           _optional_bool(self.blocked_regression, 'blocked_regression'))
        if self.baseline is not None and not isinstance(self.baseline, EvidenceRef):
            raise FeedbackError('baseline must be an EvidenceRef or None')
        if self.missed_issues is not None and self.baseline is None:
            raise FeedbackError(
                'missed_issues needs an independent comparison baseline; without '
                'one the missed-issue rate is not computable (use None)')

    @property
    def summary(self):
        return (f'{self.role} {self.category} {self.review_id} '
                f'confirmed={_render_optional(self.confirmed_issues)} '
                f'false_positive={_render_optional(self.false_positives)} '
                f'severity={self.severity}')

    def as_details(self):
        details = {
            'role': self.role,
            'schema': SCHEMA_VERSION,
            'task_id': self.review_id,
            'task_category': self.category,
            'model_id': self.identity.model_id,
            'runtime_id': self.identity.runtime_id,
            'runtime_version': self.identity.runtime_version,
            'observed_at': self.observed_at,
            'confirmed_issues': _render_optional(self.confirmed_issues),
            'false_positives': _render_optional(self.false_positives),
            'severity': self.severity,
            'missed_issues': _render_optional(self.missed_issues),
            'baseline_ref': (self.baseline.encode() if self.baseline is not None
                             else UNKNOWN),
            'blocked_regression': _render_optional_bool(self.blocked_regression),
        }
        details.update(_render_evidence(self.evidence))
        return details


@dataclass(frozen=True)
class MasterOutcome:
    """Planning signals confirmed by task evidence (design §9, third bullet)."""

    cycle_id: str
    category: str
    identity: ModelIdentity
    observed_at: str
    signals: tuple = ()
    evidence: tuple = ()
    scope_id: str = ''

    role = ROLE_MASTER

    def __post_init__(self):
        _token(self.cycle_id, 'cycle_id')
        object.__setattr__(self, 'observed_at', _validate_outcome(
            self.category, self.identity, self.observed_at, self.evidence))
        object.__setattr__(self, 'evidence', _evidence_tuple(self.evidence))
        seen = set()
        for name, count, ref in self.signals:
            if name not in MASTER_SIGNALS:
                raise FeedbackError(
                    f'unknown master signal {name!r}; expected one of {MASTER_SIGNALS}')
            if name in seen:
                raise FeedbackError(f'master signal {name!r} is recorded twice')
            seen.add(name)
            _count(count, name)
            if count is not None and not isinstance(ref, EvidenceRef):
                raise FeedbackError(
                    f'{name}: a recorded signal needs its own evidence reference')
        object.__setattr__(self, 'signals', tuple(self.signals))

    @property
    def summary(self):
        rendered = ', '.join(
            f'{name}={_render_optional(count)}' for name, count, _ in self.signals
        ) or '(no signal)'
        return f'{self.role} {self.category} {self.cycle_id} {rendered}'

    def as_details(self):
        details = {
            'role': self.role,
            'schema': SCHEMA_VERSION,
            'task_id': self.cycle_id,
            'task_category': self.category,
            'model_id': self.identity.model_id,
            'runtime_id': self.identity.runtime_id,
            'runtime_version': self.identity.runtime_version,
            'observed_at': self.observed_at,
            'signal_count': str(len(self.signals)),
        }
        for index, (name, count, ref) in enumerate(self.signals, start=1):
            details[f'signal_{index}'] = (
                f'{name}|{_render_optional(count)}|{ref.encode()}')
        details.update(_render_evidence(self.evidence))
        return details


def _render_optional(value):
    return UNKNOWN if value is None else str(value)


def _render_optional_bool(value):
    return UNKNOWN if value is None else str(bool(value)).lower()


def _render_evidence(evidence):
    rendered = {'evidence_count': str(len(evidence))}
    for index, item in enumerate(evidence, start=1):
        rendered[f'evidence_{index}'] = item.encode()
    return rendered


# --- policy ------------------------------------------------------------------
@dataclass(frozen=True)
class FeedbackPolicy:
    """When an observation is fresh enough and a sample is large enough.

    ``min_samples`` reuses S2's ``PROJECT_MIN_SAMPLES``: the project already
    treats two successful tasks as an anecdote, and a second threshold here
    would give the same question two answers.
    """

    min_samples: int = PROJECT_MIN_SAMPLES
    window_days: int = 90
    allow_ranking: bool = True

    def __post_init__(self):
        if isinstance(self.min_samples, bool) or not isinstance(self.min_samples, int) \
                or self.min_samples < 1:
            raise FeedbackError('min_samples must be an integer >= 1')
        if isinstance(self.window_days, bool) or not isinstance(self.window_days, int) \
                or self.window_days < 1:
            raise FeedbackError('window_days must be an integer >= 1')

    def as_dict(self):
        return {'min_samples': self.min_samples, 'window_days': self.window_days,
                'allow_ranking': self.allow_ranking}


# --- metrics -----------------------------------------------------------------
@dataclass(frozen=True)
class Metric:
    """One explainable number, or an explicit statement of why there is none."""

    name: str
    role: str
    category: str
    status: str
    value: float | str = UNKNOWN
    unit: str = UNKNOWN
    sample_size: int = 0
    missing: int = 0
    coverage: float = 0.0
    window_start: str = ''
    window_end: str = ''
    note: str = ''

    def __post_init__(self):
        if self.status not in METRIC_STATUSES:
            raise FeedbackError(f'unknown metric status {self.status!r}')

    @property
    def ok(self):
        return self.status == 'OK'

    def as_dict(self):
        return {
            'name': self.name,
            'role': self.role,
            'category': self.category,
            'status': self.status,
            'value': self.value,
            'unit': self.unit,
            'sample_size': self.sample_size,
            'missing': self.missing,
            'coverage': self.coverage,
            'window_start': self.window_start,
            'window_end': self.window_end,
            'note': self.note,
        }


def _metric(name, role, category, entries, values, *, unit, window, policy,
            aggregator='mean', status_override=None, note=''):
    total = len(entries)
    known = [value for value in values if value is not None]
    missing = total - len(known)
    coverage = round(len(known) / total, 3) if total else 0.0
    base = dict(name=name, role=role, category=category, unit=unit,
                sample_size=len(known), missing=missing, coverage=coverage,
                window_start=window[0], window_end=window[1])
    if status_override is not None:
        return Metric(status=status_override, note=note, **base)
    if not total:
        return Metric(status='NO_DATA', note=note or 'no recorded task in this cohort',
                      **base)
    if len(known) < policy.min_samples:
        return Metric(
            status='INSUFFICIENT_SAMPLE',
            note=(note + '; ' if note else '') +
                 f'{len(known)} sample(s) < min_samples={policy.min_samples}; '
                 'no value is inferred',
            **base)
    value = _aggregate(known, aggregator)
    return Metric(status='OK', value=value, note=note, **base)


def _aggregate(values, aggregator):
    if aggregator == 'sum':
        return float(sum(values))
    return round(sum(values) / len(values), 3)


def _mean_of_optional(entries, attribute):
    return [getattr(entry, attribute) for entry in entries]


def _rate_of_optional(entries, attribute, positive):
    values = []
    for entry in entries:
        raw = getattr(entry, attribute)
        if raw is None:
            values.append(None)
        else:
            values.append(1.0 if raw == positive else 0.0)
    return values


@dataclass(frozen=True)
class Cohort:
    """One role's observations for one task category and one exact identity."""

    role: str
    category: str
    identity: ModelIdentity
    entries: tuple
    metrics: dict = field(default_factory=dict)
    stale_entries: int = 0
    severity_counts: tuple = ()
    window_start: str = ''
    window_end: str = ''

    @property
    def sample_size(self):
        return len(self.entries)

    def metric(self, name):
        return self.metrics.get(name)

    def as_dict(self):
        return {
            'role': self.role,
            'category': self.category,
            'identity': self.identity.as_dict(),
            'sample_size': self.sample_size,
            'stale_entries': self.stale_entries,
            'severity_counts': [{'severity': name, 'count': count}
                                for name, count in self.severity_counts],
            'metrics': {name: metric.as_dict() for name, metric in self.metrics.items()},
        }


@dataclass(frozen=True)
class ComparisonRow:
    identity: ModelIdentity
    value: float
    sample_size: int
    coverage: float

    def as_dict(self):
        return {'identity': self.identity.as_dict(), 'value': self.value,
                'sample_size': self.sample_size, 'coverage': self.coverage}


@dataclass(frozen=True)
class Comparison:
    """A ranking is only produced when nothing about it is a guess."""

    role: str
    category: str
    metric: str
    allowed: bool
    rows: tuple = ()
    blocked_reasons: tuple = ()
    unit: str = UNKNOWN
    note: str = ('advisory only: one window is not a verdict, no role is '
                 'permanently best and nothing is applied automatically')

    def as_dict(self):
        return {'role': self.role, 'category': self.category,
                'metric': self.metric, 'allowed': self.allowed,
                'unit': self.unit, 'blocked_reasons': list(self.blocked_reasons),
                'rows': [row.as_dict() for row in self.rows], 'note': self.note}


@dataclass(frozen=True)
class Recommendation:
    """A readable suggestion; it changes no prompt, permission or model."""

    role: str
    category: str
    statement: str
    status: str
    basis: tuple = ()
    sample_size: int = 0
    coverage: float = 0.0
    advisory: bool = True
    applied: bool = False

    def as_dict(self):
        return {'role': self.role, 'category': self.category,
                'statement': self.statement, 'status': self.status,
                'basis': list(self.basis), 'sample_size': self.sample_size,
                'coverage': self.coverage, 'advisory': self.advisory,
                'applied': self.applied}


# --- writing -----------------------------------------------------------------
def _guard_scope(store, outcome):
    declared = getattr(outcome, 'scope_id', '') or ''
    if declared and declared != store.scope_id:
        raise FeedbackScopeError(
            'refusing a cross-scope record: the outcome belongs to another scope; '
            'records are never merged or inherited across scopes')


def record_outcome(store, outcome, *, now=None, record_id=None):
    """Append one outcome to this scope's ``observed-performance.md``.

    A write failure raises :class:`FeedbackWriteError`: the caller must report
    that the audit trail is incomplete instead of claiming it was written.
    """
    if not isinstance(outcome, (ExecutionOutcome, ReviewerOutcome, MasterOutcome)):
        raise FeedbackError(f'unknown outcome type {type(outcome).__name__}')
    _guard_scope(store, outcome)
    try:
        return store.append_record(
            FEEDBACK_DOCUMENT, summary=outcome.summary, source_class='OBSERVED',
            status='RECORDED', details=outcome.as_details(),
            record_id=record_id, now=now)
    except StoreError as exc:
        raise FeedbackWriteError(
            f'feedback for {outcome.role}/{outcome.category} was not written: {exc}'
        ) from exc


# --- reading -----------------------------------------------------------------
@dataclass(frozen=True)
class LoadResult:
    scope_id: str
    outcomes: tuple = ()
    diagnostics: tuple = ()
    ignored: int = 0

    @property
    def unknown(self):
        """Unreadable or foreign records make the history incomplete."""
        return bool(self.diagnostics)


def _parse_int(value, label):
    if value == UNKNOWN or value == '':
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise FeedbackError(f'{label} is not an integer: {value!r}') from exc
    return _count(parsed, label)


def _parse_bool(value, label):
    if value == UNKNOWN or value == '':
        return None
    if value not in ('true', 'false'):
        raise FeedbackError(f'{label} is not true/false: {value!r}')
    return value == 'true'


def _parse_cost(details):
    amount = details.get('cost_amount', UNKNOWN)
    if amount == UNKNOWN:
        return None
    try:
        parsed = float(amount)
    except (TypeError, ValueError) as exc:
        raise FeedbackError(f'cost_amount is not a number: {amount!r}') from exc
    return Cost(amount=parsed,
                currency=details.get('cost_currency', UNKNOWN),
                unit=details.get('cost_unit', UNKNOWN))


def _parse_evidence(details):
    items = []
    count = _parse_int(details.get('evidence_count', '0'), 'evidence_count') or 0
    for index in range(1, count + 1):
        key = f'evidence_{index}'
        if key not in details:
            raise FeedbackError(f'missing {key}')
        items.append(EvidenceRef.decode(details[key]))
    return tuple(items)


def _parse_baseline(details):
    raw = details.get('baseline_ref', UNKNOWN)
    if raw == UNKNOWN or not raw:
        return None
    return EvidenceRef.decode(raw)


def _parse_signals(details):
    signals = []
    count = _parse_int(details.get('signal_count', '0'), 'signal_count') or 0
    for index in range(1, count + 1):
        key = f'signal_{index}'
        raw = details.get(key)
        if not raw:
            raise FeedbackError(f'missing {key}')
        parts = raw.split('|', 2)
        if len(parts) != 3:
            raise FeedbackError(f'unreadable {key}: {raw!r}')
        name, rendered, encoded = parts
        count_value = None
        if rendered != UNKNOWN:
            try:
                count_value = int(rendered)
            except ValueError as exc:
                raise FeedbackError(
                    f'{key} count is not an integer: {rendered!r}') from exc
        ref = None if encoded == UNKNOWN else EvidenceRef.decode(encoded)
        signals.append((name, count_value, ref))
    return tuple(signals)


def _identity_from(details):
    return ModelIdentity(
        model_id=details.get('model_id', UNKNOWN),
        runtime_id=details.get('runtime_id', UNKNOWN),
        runtime_version=details.get('runtime_version', UNKNOWN))


def _parse_record(record):
    details = dict(record.details)
    schema = details.get('schema')
    if not schema:
        raise FeedbackError(
            'not a feedback record (no schema marker); left untouched')
    if schema != SCHEMA_VERSION:
        raise FeedbackError(
            f'schema {schema!r} is not {SCHEMA_VERSION!r}: read-only diagnostic, '
            'a migration decision is required before these records are used')
    role = details.get('role')
    category = details.get('task_category')
    identity = _identity_from(details)
    observed_at = details.get('observed_at', '')
    evidence = _parse_evidence(details)
    if role == ROLE_EXECUTION:
        return ExecutionOutcome(
            task_id=details.get('task_id', ''),
            category=category,
            identity=identity,
            observed_at=observed_at,
            evidence=evidence,
            first_acceptance=details.get('first_acceptance', UNKNOWN),
            rework_rounds=_parse_int(details.get('rework_rounds'), 'rework_rounds'),
            post_merge_regression_defects=_parse_int(
                details.get('regression_defects'), 'regression_defects'),
            duration_seconds=_parse_int(
                details.get('duration_seconds'), 'duration_seconds'),
            cost=_parse_cost(details))
    if role == ROLE_REVIEWER:
        missed = _parse_int(details.get('missed_issues'), 'missed_issues')
        baseline = _parse_baseline(details)
        if missed is not None and baseline is None:
            raise FeedbackError(
                'missed_issues without a comparison baseline is not usable; '
                'the record is reported instead of guessed')
        return ReviewerOutcome(
            review_id=details.get('task_id', ''),
            category=category,
            identity=identity,
            observed_at=observed_at,
            evidence=evidence,
            confirmed_issues=_parse_int(
                details.get('confirmed_issues'), 'confirmed_issues'),
            false_positives=_parse_int(
                details.get('false_positives'), 'false_positives'),
            severity=details.get('severity', UNKNOWN),
            missed_issues=missed,
            baseline=baseline,
            blocked_regression=_parse_bool(
                details.get('blocked_regression'), 'blocked_regression'))
    if role == ROLE_MASTER:
        return MasterOutcome(
            cycle_id=details.get('task_id', ''),
            category=category,
            identity=identity,
            observed_at=observed_at,
            signals=_parse_signals(details),
            evidence=evidence)
    raise FeedbackError(f'unknown role {role!r} in a feedback record')


def load_outcomes(store):
    """Read this scope's feedback records; never reads another scope."""
    diagnostics = []
    state = store.read_document(FEEDBACK_DOCUMENT)
    if not state.exists:
        return LoadResult(scope_id=store.scope_id,
                          diagnostics=(f'{FEEDBACK_DOCUMENT}: document does not '
                                       'exist (not a PASS)',))
    if state.issues:
        return LoadResult(scope_id=store.scope_id,
                          diagnostics=tuple(state.issues))
    outcomes, ignored = [], 0
    for record in state.records:
        if record.status == 'SUPERSEDED':
            ignored += 1
            continue
        if record.source_class != 'OBSERVED':
            diagnostics.append(
                f'{record.record_id}: source_class {record.source_class!r} is not '
                'OBSERVED; excluded from calibration')
            ignored += 1
            continue
        try:
            outcomes.append(_parse_record(record))
        except FeedbackError as exc:
            diagnostics.append(f'{record.record_id}: {exc}')
            ignored += 1
    return LoadResult(scope_id=store.scope_id, outcomes=tuple(outcomes),
                      diagnostics=tuple(diagnostics), ignored=ignored)


# --- reporting ---------------------------------------------------------------
@dataclass(frozen=True)
class FeedbackReport:
    """An explainable, advisory view of one scope's own history."""

    scope_id: str
    window_start: str
    window_end: str
    policy: FeedbackPolicy
    cohorts: tuple = ()
    recommendations: tuple = ()
    degradations: tuple = ()
    diagnostics: tuple = ()
    stale_entries: int = 0
    ignored_records: int = 0
    applied_automatically: bool = False
    changes_configuration: bool = False
    notes: tuple = ()

    def cohort(self, role, category=None):
        for item in self.cohorts:
            if item.role != role:
                continue
            if category is None or item.category == category:
                return item
        return None

    def cohorts_for(self, role):
        return tuple(item for item in self.cohorts if item.role == role)

    def compare(self, role, category, metric_name):
        rows, blocked = [], []
        cohorts = [item for item in self.cohorts
                   if item.role == role and item.category == category]
        if not self.policy.allow_ranking:
            blocked.append('ranking is disabled by policy')
        if not cohorts:
            blocked.append('no cohort for this role / task category')
        for item in cohorts:
            metric = item.metric(metric_name)
            if metric is None:
                blocked.append(f'{item.identity.key}: metric {metric_name!r} is unknown')
            elif not metric.ok:
                blocked.append(
                    f'{item.identity.key}: {metric_name}={metric.status}')
            elif not item.identity.known:
                blocked.append(f'{item.identity.key}: model / runtime identity is UNKNOWN')
            else:
                rows.append(ComparisonRow(
                    identity=item.identity, value=metric.value,
                    sample_size=metric.sample_size, coverage=metric.coverage))
        units = {item.metric(metric_name).unit for item in cohorts
                 if item.metric(metric_name) is not None}
        if len(units) > 1:
            blocked.append(f'mixed units {sorted(units)}; numbers are not comparable')
        if len(rows) < 2:
            blocked.append('fewer than two comparable identities')
        direction = METRIC_DIRECTIONS.get(metric_name, 'higher')
        ordered = tuple(sorted(rows, key=lambda row: row.value,
                               reverse=direction == 'higher'))
        unit = units.pop() if len(units) == 1 else UNKNOWN
        return Comparison(role=role, category=category, metric=metric_name,
                          allowed=not blocked, rows=() if blocked else ordered,
                          blocked_reasons=tuple(blocked), unit=unit)

    def as_dict(self):
        return {
            'scope_id': self.scope_id,
            'window': {'start': self.window_start, 'end': self.window_end},
            'policy': self.policy.as_dict(),
            'cohorts': [item.as_dict() for item in self.cohorts],
            'recommendations': [item.as_dict() for item in self.recommendations],
            'degradations': list(self.degradations),
            'diagnostics': list(self.diagnostics),
            'stale_entries': self.stale_entries,
            'ignored_records': self.ignored_records,
            'applied_automatically': self.applied_automatically,
            'changes_configuration': self.changes_configuration,
            'notes': list(self.notes),
        }

    def render_lines(self):
        lines = [
            f'scope: {self.scope_id}',
            f'window: {self.window_start} .. {self.window_end} '
            f'min_samples={self.policy.min_samples}',
        ]
        for item in self.cohorts:
            lines.append(
                f'{item.role} {item.category} '
                f'{item.identity.model_id}/{item.identity.runtime_version}: '
                f'samples={item.sample_size} stale={item.stale_entries}')
            for metric in item.metrics.values():
                rendered = metric.value if metric.ok else metric.status
                lines.append(
                    f'  {metric.name}={rendered} unit={metric.unit} '
                    f'samples={metric.sample_size} missing={metric.missing} '
                    f'coverage={metric.coverage}')
        for recommendation in self.recommendations:
            lines.append(f'recommendation[{recommendation.status}]: '
                         f'{recommendation.statement}')
        for degradation in self.degradations:
            lines.append(f'degradation: {degradation}')
        for diagnostic in self.diagnostics:
            lines.append(f'diagnostic: {diagnostic}')
        lines.append('applied_automatically=False changes_configuration=False')
        return lines


def _group_key(outcome):
    return (outcome.role, outcome.category, outcome.identity.key)


def _build_cohort(role, category, identity, entries, *, window, policy,
                  current_identity=None):
    fresh = [entry for entry in entries
             if _parse_utc(entry.observed_at) >= _parse_utc(window[0])]
    stale = len(entries) - len(fresh)
    metrics = {}
    if not fresh:
        for name in METRICS_BY_ROLE[role]:
            metrics[name] = _metric(
                name, role, category, entries, [], unit='UNKNOWN', window=window,
                policy=policy, status_override='STALE',
                note='every record in this cohort is older than the window')
        return Cohort(role=role, category=category, identity=identity,
                      entries=tuple(entries), metrics=metrics,
                      stale_entries=stale, window_start=window[0],
                      window_end=window[1])

    identity_note = ''
    if not identity.known:
        identity_note = ('model / runtime identity is UNKNOWN, so this evidence '
                         'cannot be attributed to a model')
    elif current_identity is not None and current_identity.key != identity.key:
        identity_note = (
            f'recorded identity {identity.key} differs from the identity now in '
            f'use ({current_identity.key}); no evaluation is carried forward')

    severity_counts = ()
    if role == ROLE_EXECUTION:
        metrics['first_acceptance_pass_rate'] = _metric(
            'first_acceptance_pass_rate', role, category, fresh,
            _rate_of_optional(fresh, 'first_acceptance', 'PASS'),
            unit='share(tasks)', window=window, policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note)
        metrics['mean_rework_rounds'] = _metric(
            'mean_rework_rounds', role, category, fresh,
            _mean_of_optional(fresh, 'rework_rounds'),
            unit='rounds/task', window=window, policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note)
        metrics['post_merge_regression_defect_rate'] = _metric(
            'post_merge_regression_defect_rate', role, category, fresh,
            _mean_of_optional(fresh, 'post_merge_regression_defects'),
            unit='defects/task', window=window, policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note or 'a merge that simply landed is not a quality signal')
        metrics['mean_delivery_seconds'] = _metric(
            'mean_delivery_seconds', role, category, fresh,
            _mean_of_optional(fresh, 'duration_seconds'),
            unit='seconds/task', window=window, policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note or 'only recorded when the runtime really measured it')
        metrics['mean_cost'] = _cost_metric(role, category, fresh, window, policy,
                                           identity_note)
    elif role == ROLE_REVIEWER:
        pooled = [(entry.confirmed_issues, entry.false_positives) for entry in fresh]
        denominators = [c + f for c, f in pooled if c is not None and f is not None]
        confirmed_values = [
            (c / (c + f) if c + f else None)
            for c, f in pooled if c is not None and f is not None]
        metrics['confirmed_issue_rate'] = _metric(
            'confirmed_issue_rate', role, category, fresh, confirmed_values,
            unit='confirmed/(confirmed+false_positive)', window=window,
            policy=policy, aggregator='mean',
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note or f'pooled over {len(denominators)} review(s) '
                                  'with both counts recorded')
        false_positive_values = [
            (f / (c + f) if c + f else None)
            for c, f in pooled if c is not None and f is not None]
        metrics['false_positive_rate'] = _metric(
            'false_positive_rate', role, category, fresh, false_positive_values,
            unit='false_positive/(confirmed+false_positive)', window=window,
            policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note or 'a confirmed finding and a false positive are '
                                  'counted separately')
        comparators = [entry for entry in fresh
                       if entry.missed_issues is not None
                       and entry.baseline is not None]
        if not comparators:
            metrics['mean_missed_issues_per_review'] = _metric(
                'mean_missed_issues_per_review', role, category, fresh, [],
                unit='missed/review', window=window, policy=policy,
                status_override='NO_COMPARATOR',
                note='no independent comparison baseline was supplied, so the '
                     'missed-issue count is not computed')
        else:
            metrics['mean_missed_issues_per_review'] = _metric(
                'mean_missed_issues_per_review', role, category, comparators,
                _mean_of_optional(comparators, 'missed_issues'),
                unit='missed/review', window=window, policy=policy,
                status_override='IDENTITY_CHANGED' if identity_note else None,
                note=identity_note or f'{len(comparators)} review(s) with a '
                                      'comparison baseline')
        metrics['regression_blocked_rate'] = _metric(
            'regression_blocked_rate', role, category, fresh,
            _rate_of_optional(fresh, 'blocked_regression', True),
            unit='share(reviews)', window=window, policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note)
        severity_values = [
            1.0 if entry.severity == 'HIGH' else 0.0
            for entry in fresh if entry.severity != UNKNOWN]
        counts = {}
        for entry in fresh:
            counts[entry.severity] = counts.get(entry.severity, 0) + 1
        severity_counts = tuple(sorted(counts.items()))
        metrics['high_severity_share'] = _metric(
            'high_severity_share', role, category, fresh, severity_values,
            unit='share(reviews)', window=window, policy=policy,
            status_override='IDENTITY_CHANGED' if identity_note else None,
            note=identity_note or 'severity of the confirmed findings')
    else:
        for name in METRICS_BY_ROLE[role]:
            signal_name = MASTER_SIGNAL_FOR_METRIC[name]
            values = []
            for entry in fresh:
                values.append(next(
                    (count for signal, count, _ in entry.signals
                     if signal == signal_name), None))
            metrics[name] = _metric(
                name, role, category, fresh, values, unit='count/cycle',
                window=window, policy=policy,
                status_override='IDENTITY_CHANGED' if identity_note else None,
                note=identity_note or 'planning signals confirmed by task '
                                      'evidence; a single cycle is an anecdote')
    return Cohort(role=role, category=category, identity=identity,
                  entries=tuple(entries), metrics=metrics, stale_entries=stale,
                  severity_counts=severity_counts, window_start=window[0],
                  window_end=window[1])


def _cost_metric(role, category, entries, window, policy, identity_note):
    unit_keys = {f'{entry.cost.currency}/{entry.cost.unit}'
                 for entry in entries if entry.cost is not None}
    if len(unit_keys) > 1:
        return _metric(
            'mean_cost', role, category, entries, [], unit='mixed',
            window=window, policy=policy, status_override='NOT_COMPARABLE',
            note=(f'mixed price units {sorted(unit_keys)}; costs are never '
                  'averaged across currencies or units'))
    values = [entry.cost.amount for entry in entries if entry.cost is not None]
    unit = unit_keys.pop() if unit_keys else UNKNOWN
    return _metric(
        'mean_cost', role, category, entries, values, unit=unit, window=window,
        policy=policy,
        status_override='IDENTITY_CHANGED' if identity_note else None,
        note=identity_note or 'only recorded when a real cost was collected; '
                              'never estimated')


def _recommendations_for(cohort, policy):
    recommendations = []
    if cohort.role == ROLE_EXECUTION:
        pass_rate = cohort.metric('first_acceptance_pass_rate')
        if pass_rate is None:
            return recommendations
        if pass_rate.ok:
            statement = (
                f'{cohort.category}: first-acceptance pass rate '
                f'{pass_rate.value:.3f} over {pass_rate.sample_size} task(s) '
                f'(coverage {pass_rate.coverage}); '
                + ('every recorded task passed first time — keep monitoring, '
                   'this is not a permanent verdict'
                   if pass_rate.value >= 1.0 else
                   'rework is visible in this category; review the failing tasks '
                   'before changing anything'))
            recommendations.append(Recommendation(
                role=cohort.role, category=cohort.category, statement=statement,
                status='ADVISORY',
                basis=('first_acceptance_pass_rate',),
                sample_size=pass_rate.sample_size, coverage=pass_rate.coverage))
        else:
            recommendations.append(Recommendation(
                role=cohort.role, category=cohort.category,
                statement=(f'{cohort.category}: first-acceptance pass rate is '
                           f'{pass_rate.status.lower()} ({pass_rate.sample_size} '
                           f'sample(s), coverage {pass_rate.coverage}); no '
                           'conclusion is drawn'),
                status=pass_rate.status, basis=('first_acceptance_pass_rate',),
                sample_size=pass_rate.sample_size, coverage=pass_rate.coverage))
    elif cohort.role == ROLE_REVIEWER:
        confirmed = cohort.metric('confirmed_issue_rate')
        missed = cohort.metric('mean_missed_issues_per_review')
        if confirmed is not None:
            if confirmed.ok:
                statement = (
                    f'{cohort.category}: confirmed finding rate '
                    f'{confirmed.value:.3f} over {confirmed.sample_size} review(s) '
                    f'(coverage {confirmed.coverage}); a merge or a green CI run '
                    'is not counted as review quality')
                recommendations.append(Recommendation(
                    role=cohort.role, category=cohort.category, statement=statement,
                    status='ADVISORY', basis=('confirmed_issue_rate',),
                    sample_size=confirmed.sample_size, coverage=confirmed.coverage))
            else:
                recommendations.append(Recommendation(
                    role=cohort.role, category=cohort.category,
                    statement=(f'{cohort.category}: confirmed finding rate is '
                               f'{confirmed.status.lower()} '
                               f'({confirmed.sample_size} sample(s), coverage '
                               f'{confirmed.coverage}); no conclusion is drawn'),
                    status=confirmed.status, basis=('confirmed_issue_rate',),
                    sample_size=confirmed.sample_size,
                    coverage=confirmed.coverage))
        if missed is not None and missed.status == 'NO_COMPARATOR':
            recommendations.append(Recommendation(
                role=cohort.role, category=cohort.category,
                statement=(f'{cohort.category}: missed-issue count is not '
                           'computable without an independent comparison baseline; '
                           'no miss rate or detection rate is reported'),
                status='NO_COMPARATOR',
                basis=('mean_missed_issues_per_review',), sample_size=0,
                coverage=0.0))
    elif cohort.role == ROLE_MASTER:
        named = [(name, cohort.metric(name))
                 for name in METRICS_BY_ROLE[ROLE_MASTER]]
        ready = [(name, metric) for name, metric in named if metric is not None
                 and metric.ok]
        if ready:
            detail = ', '.join(
                f'{name}={metric.value:g} over {metric.sample_size} cycle(s)'
                for name, metric in ready)
            recommendations.append(Recommendation(
                role=cohort.role, category=cohort.category,
                statement=(f'{cohort.category}: {detail}; one cycle is an '
                           'anecdote, so no stable quality is inferred'),
                status='ADVISORY', basis=tuple(name for name, _ in ready),
                sample_size=max(metric.sample_size for _, metric in ready),
                coverage=max(metric.coverage for _, metric in ready)))
        else:
            statuses = sorted({metric.status for _, metric in named
                               if metric is not None})
            recommendations.append(Recommendation(
                role=cohort.role, category=cohort.category,
                statement=(f'{cohort.category}: planning signals are not '
                           f'computable ({", ".join(statuses) or UNKNOWN}); no '
                           'stable quality is inferred from a single result'),
                status='INSUFFICIENT_SAMPLE' if statuses else 'NO_DATA',
                basis=(), sample_size=cohort.sample_size, coverage=0.0))
    return recommendations


def build_report(store, *, now=None, policy=None, outcomes=None,
                 current_identities=None):
    """Build one scope's advisory report from real records only.

    ``outcomes`` exists for the fixed synthetic tests; when it is omitted the
    report reads this store's own document. Either way the outcomes are checked
    against ``store.scope_id`` before they can influence a number.
    """
    policy = policy or FeedbackPolicy()
    end = _timestamp(now, 'now') if now is not None else local_store.utc_timestamp()
    window = (local_store.utc_timestamp(
        _parse_utc(end) - timedelta(days=policy.window_days)), end)
    if outcomes is None:
        loaded = load_outcomes(store)
        diagnostics = list(loaded.diagnostics)
        ignored = loaded.ignored
        records = list(loaded.outcomes)
    else:
        diagnostics, ignored = [], 0
        records = list(outcomes)
        for outcome in records:
            _guard_scope(store, outcome)
    for outcome in records:
        if not isinstance(outcome, (ExecutionOutcome, ReviewerOutcome,
                                    MasterOutcome)):
            raise FeedbackError(f'unknown outcome type {type(outcome).__name__}')

    stale = sum(1 for outcome in records
                if _parse_utc(outcome.observed_at) < _parse_utc(window[0]))
    groups = {}
    for outcome in records:
        groups.setdefault(_group_key(outcome), []).append(outcome)

    cohorts, degradations, recommendations = [], [], []
    for (role, category, _key), entries in sorted(groups.items()):
        identity = entries[0].identity
        current = (current_identities or {}).get(role)
        cohort = _build_cohort(role, category, identity, entries,
                               window=window, policy=policy,
                               current_identity=current)
        cohorts.append(cohort)
        for metric in cohort.metrics.values():
            if metric.status != 'OK':
                degradations.append(
                    f'{role}/{category}: {metric.name}={metric.status} '
                    f'(samples={metric.sample_size}, missing={metric.missing}, '
                    f'coverage={metric.coverage})')
        recommendations.extend(_recommendations_for(cohort, policy))

    if not cohorts:
        degradations.append(
            'no data: this scope has no usable feedback record; coverage is 0 '
            'and no rate is reported')
    if stale:
        degradations.append(
            f'{stale} record(s) are older than the {policy.window_days}-day '
            f'window; they are not counted as current evidence')

    notes = [
        'advisory only: nothing here changes a prompt, a permission or a model '
        'configuration',
        'records are per scope; they are not merged, synchronised, committed or '
        'packaged',
        'chat memory, self-assessment, a merge event and a green CI run are not '
        'quality evidence on their own',
        'cohorts are keyed by role + task category + exact model / runtime '
        'identity; external benchmark indices are never pooled into these '
        'project-internal numbers',
    ]
    return FeedbackReport(
        scope_id=store.scope_id, window_start=window[0], window_end=window[1],
        policy=policy, cohorts=tuple(cohorts),
        recommendations=tuple(recommendations),
        degradations=tuple(degradations), diagnostics=tuple(diagnostics),
        stale_entries=stale, ignored_records=ignored, notes=tuple(notes))
