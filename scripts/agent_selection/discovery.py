#!/usr/bin/env python3
"""Agent discovery with an explicit-registry fallback (#121, S2).

Design contract: ``docs/design/agent-role-discovery-and-model-selection.md``
§5.1. The order is fixed and has no third option:

1. the runtime's own formal agent enumeration, when it exposes one;
2. otherwise the explicit local registry (``agent-registry.md`` in the current
   scope, or an explicitly constructed :class:`ExplicitRegistry`);
3. otherwise an explicit ``NO_ADAPTER`` / ``EMPTY`` result.

There is no default agent, no catalog bundled into the code and no inference
from prompt names, file names or configuration keys. Discovery is also not
recommendation: the candidates returned here are handed to
``scripts.agent_selection.roles`` unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from .local_store import StoreError
from .runtime_adapter import (
    AgentCandidate,
    CapabilityRecord,
    CANDIDATE_SOURCES,
    DiscoveryResult,
    EVIDENCE_CLASSES,
    PermissionScope,
    RuntimeAdapter,
    RuntimeAdapterError,
    parse_timestamp,
)

__all__ = [
    'REGISTRY_DOCUMENT',
    'DISCOVERY_RUNTIME',
    'DISCOVERY_REGISTRY',
    'DISCOVERY_NO_ADAPTER',
    'DISCOVERY_EMPTY',
    'DISCOVERY_ERROR',
    'REGISTRY_DETAIL_KEYS',
    'RegistryError',
    'ExplicitRegistry',
    'DiscoveryReport',
    'discover_candidates',
    'registry_candidates_from_records',
]

REGISTRY_DOCUMENT = 'agent-registry.md'

DISCOVERY_RUNTIME = 'RUNTIME'
DISCOVERY_REGISTRY = 'REGISTRY'
DISCOVERY_NO_ADAPTER = 'NO_ADAPTER'
DISCOVERY_EMPTY = 'EMPTY'
DISCOVERY_ERROR = 'ERROR'
REPORT_OUTCOMES = (DISCOVERY_RUNTIME, DISCOVERY_REGISTRY, DISCOVERY_NO_ADAPTER,
                   DISCOVERY_EMPTY, DISCOVERY_ERROR)

# The exact detail keys one registry record may carry. Every key is a plain
# scalar so the Markdown store stays human-readable; nothing is parsed out of
# prose.
REGISTRY_DETAIL_KEYS = (
    'runtime_id', 'runtime_version', 'agent_id', 'model_id', 'model_family',
    'modalities', 'tools', 'read_paths', 'write_paths', 'commands', 'network',
    'read_only', 'context_tokens', 'cost_per_mtok', 'latency_ms',
    'capability_ref', 'evidence_time', 'source_class',
)
REQUIRED_REGISTRY_KEYS = ('runtime_id', 'runtime_version', 'agent_id',
                          'model_id', 'evidence_time')


class RegistryError(ValueError):
    """One registry record is not usable as an agent definition."""


def _csv(value):
    return tuple(part.strip() for part in str(value).split(',')
                 if part.strip())


def _strict_bool(value, key):
    text = str(value).strip().lower()
    if text == 'true':
        return True
    if text == 'false':
        return False
    raise RegistryError(f'{key} must be true or false, got {value!r}')


def _optional_int(value, key):
    if value is None or str(value).strip() == '':
        return None
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise RegistryError(f'{key} must be an integer, got {value!r}') from exc
    if parsed < 0:
        raise RegistryError(f'{key} must not be negative')
    return parsed


def _optional_float(value, key):
    if value is None or str(value).strip() == '':
        return None
    try:
        parsed = float(str(value).strip())
    except ValueError as exc:
        raise RegistryError(f'{key} must be a number, got {value!r}') from exc
    if parsed < 0:
        raise RegistryError(f'{key} must not be negative')
    return parsed


@dataclass(frozen=True)
class ExplicitRegistry:
    """An explicitly configured agent registry.

    ``entries`` are already-validated candidates. ``issues`` records entries
    that could not be used, so a partial registry is reported rather than
    silently treated as complete.
    """

    entries: tuple[AgentCandidate, ...] = ()
    issues: tuple[str, ...] = ()

    def __post_init__(self):
        for entry in self.entries:
            if entry.source != CANDIDATE_SOURCES[1]:
                raise RegistryError(
                    f'{entry.candidate_id}: registry entries must declare '
                    f'source={CANDIDATE_SOURCES[1]!r}')

    def discover(self) -> DiscoveryResult:
        if not self.entries:
            return DiscoveryResult(
                outcome='EMPTY', mode='explicit-registry',
                notes=tuple(self.issues) + (
                    'the explicit agent registry has no usable entry',))
        notes = tuple(self.issues) + (
            f'{len(self.entries)} entry / entries read from the explicit '
            'registry',)
        return DiscoveryResult(outcome='OK', mode='explicit-registry',
                               candidates=tuple(self.entries), notes=notes)

    @classmethod
    def from_store(cls, store, *, capability_records=None):
        """Read ``agent-registry.md`` from one initialized local scope."""
        try:
            records = store.read_records(REGISTRY_DOCUMENT)
        except StoreError as exc:
            return cls(entries=(), issues=(f'{REGISTRY_DOCUMENT}: {exc}',))
        entries, issues = registry_candidates_from_records(
            records, capability_records=capability_records)
        return cls(entries=entries, issues=issues)


def registry_candidates_from_records(records, *, capability_records=None):
    """Convert Markdown registry records into candidates (or issues).

    A record that is ``SUPERSEDED`` is skipped: an old definition must not be
    resurrected. Every other unusable record yields an issue and no candidate,
    so the selector can report the gap instead of guessing.
    """
    capabilities = dict(capability_records or {})
    entries = []
    issues = []
    for record in records:
        label = f'{REGISTRY_DOCUMENT} record {record.record_id!r}'
        if record.status == 'SUPERSEDED':
            continue
        details = dict(record.details)
        missing = [key for key in REQUIRED_REGISTRY_KEYS
                   if not str(details.get(key, '')).strip()]
        if missing:
            issues.append(f'{label}: missing {", ".join(missing)}; skipped')
            continue
        unknown_keys = sorted(set(details) - set(REGISTRY_DETAIL_KEYS))
        if unknown_keys:
            issues.append(
                f'{label}: unsupported detail key(s) {", ".join(unknown_keys)}; '
                'skipped (unknown fields are not guessed)')
            continue
        try:
            source_class = str(details.get('source_class',
                                           'OBSERVED')).strip().upper()
            if source_class not in EVIDENCE_CLASSES:
                raise RegistryError(
                    f'source_class must be one of {EVIDENCE_CLASSES}, got '
                    f'{source_class!r}')
            evidence_time = str(details['evidence_time']).strip()
            parse_timestamp(evidence_time)
            capability_ref = str(details.get('capability_ref', '')).strip()
            capability_record = capabilities.get(capability_ref)
            if capability_ref and capability_record is None:
                issues.append(
                    f'{label}: capability record {capability_ref!r} was not '
                    'found; the candidate is kept without capability evidence '
                    'and cannot be auto-selected')
            if capability_record is not None and not isinstance(
                    capability_record, CapabilityRecord):
                raise RegistryError('capability_records values must be '
                                    'CapabilityRecord instances')
            entry = AgentCandidate(
                runtime_id=str(details['runtime_id']).strip(),
                runtime_version=str(details['runtime_version']).strip(),
                agent_id=str(details['agent_id']).strip(),
                model_id=str(details['model_id']).strip(),
                model_family=(str(details['model_family']).strip()
                              if str(details.get('model_family', '')).strip()
                              else None),
                modalities=_csv(details.get('modalities', '')),
                tools=_csv(details.get('tools', '')),
                permissions=PermissionScope(
                    read_paths=_csv(details.get('read_paths', '')),
                    write_paths=_csv(details.get('write_paths', '')),
                    commands=_csv(details.get('commands', '')),
                    network=_strict_bool(details.get('network', 'false'),
                                         'network'),
                    read_only=_strict_bool(details.get('read_only', 'false'),
                                           'read_only'),
                ),
                capability_record=capability_record,
                source=CANDIDATE_SOURCES[1],
                source_class=source_class,
                evidence_time=evidence_time,
                context_tokens=_optional_int(details.get('context_tokens'),
                                             'context_tokens'),
                cost_per_mtok=_optional_float(details.get('cost_per_mtok'),
                                              'cost_per_mtok'),
                latency_ms=_optional_int(details.get('latency_ms'),
                                         'latency_ms'),
                notes=(f'registry record {record.record_id}',),
            )
        except (RegistryError, RuntimeAdapterError) as exc:
            issues.append(f'{label}: {exc}; skipped')
            continue
        entries.append(entry)
    return tuple(entries), tuple(issues)


@dataclass(frozen=True)
class DiscoveryReport:
    """The layered discovery outcome: runtime first, registry second."""

    outcome: str
    runtime_result: DiscoveryResult | None = None
    registry_result: DiscoveryResult | None = None
    candidates: tuple[AgentCandidate, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.outcome not in REPORT_OUTCOMES:
            raise ValueError(
                f'unknown discovery report outcome {self.outcome!r}; expected '
                f'one of {REPORT_OUTCOMES}')
        if self.outcome in (DISCOVERY_RUNTIME, DISCOVERY_REGISTRY) \
                and not self.candidates:
            raise ValueError(
                f'{self.outcome} requires at least one candidate')

    @property
    def discovered(self):
        return bool(self.candidates)

    @property
    def source(self):
        return (self.runtime_result.mode if self.outcome == DISCOVERY_RUNTIME
                else self.registry_result.mode
                if self.outcome == DISCOVERY_REGISTRY else None)

    def as_dict(self):
        return {
            'outcome': self.outcome,
            'source': self.source,
            'runtime_result': (self.runtime_result.as_dict()
                               if self.runtime_result is not None else None),
            'registry_result': (self.registry_result.as_dict()
                                if self.registry_result is not None else None),
            'candidates': [candidate.as_dict()
                           for candidate in self.candidates],
            'notes': list(self.notes),
        }


def _run_runtime(adapter):
    if adapter is None:
        return None, None
    try:
        if not isinstance(adapter, RuntimeAdapter):
            raise RuntimeAdapterError(
                'adapter does not implement the RuntimeAdapter contract')
        description = adapter.describe()
        result = adapter.discover()
        return description, result
    except Exception as exc:  # an adapter must not take discovery down with it
        return None, DiscoveryResult(
            outcome='ERROR', mode='runtime',
            notes=('the runtime adapter failed; no capability or agent is '
                   'inferred from the failure',),
            error=f'{type(exc).__name__}: {exc}')


def discover_candidates(adapter=None, registry=None) -> DiscoveryReport:
    """Discover candidates with the documented fallback order."""
    description, runtime_result = _run_runtime(adapter)
    notes = []
    if description is not None:
        notes.append(
            f'runtime {description.runtime_id} {description.runtime_version} '
            f'(adapter {description.adapter_id})')
        if description.can_enumerate_agents is False:
            notes.append('the runtime does not expose a formal agent '
                         'enumeration interface')
    if runtime_result is not None and runtime_result.notes:
        notes.extend(runtime_result.notes)
    if runtime_result is not None and runtime_result.error:
        notes.append(f'runtime discovery error: {runtime_result.error}')

    if runtime_result is not None and runtime_result.discovered:
        return DiscoveryReport(
            outcome=DISCOVERY_RUNTIME,
            runtime_result=runtime_result,
            candidates=tuple(runtime_result.candidates),
            notes=tuple(notes))

    registry_result = registry.discover() if registry is not None else None
    if registry_result is not None:
        notes.extend(registry_result.notes)

    if registry_result is not None and registry_result.discovered:
        notes.append('runtime discovery did not yield agents; the explicit '
                     'registry was used')
        return DiscoveryReport(
            outcome=DISCOVERY_REGISTRY,
            runtime_result=runtime_result,
            registry_result=registry_result,
            candidates=tuple(registry_result.candidates),
            notes=tuple(notes))

    if runtime_result is not None and runtime_result.outcome == 'EMPTY':
        outcome = DISCOVERY_EMPTY
        notes.append('the runtime enumerated no agents and the explicit '
                     'registry is empty; no agent is invented')
    elif runtime_result is None or runtime_result.outcome in (
            'UNSUPPORTED', 'NO_ADAPTER'):
        outcome = DISCOVERY_NO_ADAPTER
        notes.append('no usable runtime adapter and no explicit registry '
                     'entry; no agent is invented')
    elif runtime_result.outcome == 'ERROR':
        outcome = DISCOVERY_ERROR
        notes.append('runtime discovery failed and the explicit registry is '
                     'empty; no agent is invented')
    else:
        outcome = DISCOVERY_EMPTY
        notes.append('the runtime enumerated no agents and the explicit '
                     'registry is empty')
    return DiscoveryReport(outcome=outcome, runtime_result=runtime_result,
                           registry_result=registry_result,
                           candidates=(), notes=tuple(notes))
