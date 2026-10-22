#!/usr/bin/env python3
"""Static validation for the Agent-Orchestration kit (core + local/github editions)."""
from pathlib import Path
import argparse, re, sys

ROOT = Path(__file__).resolve().parents[1]
# Single source of truth for the shippable kit. This list has two jobs at once:
#   1. the structurally required files of this repository, and
#   2. the file manifest of the release package built by scripts/build_release.py.
# scripts/build_release.py parses THIS list to decide what to package, so there is
# no second manifest to maintain. Keep it in sync whenever a versioned artifact is
# added or removed. Files that must not ship (docs/, release/, the release builder
# itself, .orchestration/, .worktrees/, .workbuddy/) are simply not listed here.
REQUIRED = [
    'AGENT-BOOTSTRAP.md', 'AGENT-ORCHESTRATION-ACCEPTANCE.md', 'AGENT-ORCHESTRATION.md',
    'AGENTS.md', 'LICENSE.txt', 'ORCHESTRATION-PROJECT.md', 'README.md', 'VERSION.txt',
    'editions/github/ACTIVE-TASK-REGISTRY.md', 'editions/github/ISSUE-TEMPLATE.md',
    'editions/github/MASTER-MULTI-SESSION.md', 'editions/github/MASTER-SINGLE-SESSION.md',
    'editions/github/MASTER.md', 'editions/github/PR-TEMPLATE.md', 'editions/github/README.md',
    'editions/github/START-EXECUTION.md', 'editions/github/START-MASTER-EXISTING-PROJECT.md',
    'editions/github/START-MASTER-NEW-PROJECT.md',
    'editions/local/MASTER-MULTI-SESSION.md', 'editions/local/MASTER-SINGLE-SESSION.md',
    'editions/local/MASTER.md', 'editions/local/README.md', 'editions/local/START-EXECUTION.md',
    'editions/local/START-MASTER-EXISTING-PROJECT.md', 'editions/local/START-MASTER-NEW-PROJECT.md',
    'prompts/START-CHARTER.md', 'prompts/START-REVIEWER.md',
    'scripts/orchestrator.py', 'scripts/validate_kit.py',
    'templates/DESIGN.md', 'templates/ORCHESTRATION-PROJECT.template.md', 'templates/PLAN.md',
    'templates/PROJECT-CHARTER.md', 'templates/REVIEW-CHECKLIST.md', 'templates/TASK-PACKET.md',
    'templates/gitignore.snippet',
    'tests/test_orchestrator.py', 'tests/test_validate_kit.py',
]

# --- Evidence matrix contract -------------------------------------------------
# The field names, the status enum and the G1 rules are defined once, in
# AGENT-ORCHESTRATION.md 4.1. This module reads that definition back (it does not
# restate it) and enforces it on the local/github task templates. If the doc drifts
# away from the contract floor below, validation fails instead of silently
# accepting a second definition.
CORE_DOC = 'AGENT-ORCHESTRATION.md'
TASK_PACKET_DOC = 'templates/TASK-PACKET.md'
ISSUE_TEMPLATE_DOC = 'editions/github/ISSUE-TEMPLATE.md'
EVIDENCE_FIELD_ANCHOR = '证据条目（evidence item）字段'
PACKET_FIELD_ANCHOR = '任务包结构化扩展字段'
# Contract floor for `status`. A silently narrowed or extended enum is reported.
STATUS_VALUES = ('PASS', 'FAIL', 'NOT_RUN', 'BLOCKED', 'NOT_APPLICABLE')
NON_PASS_STATUSES = ('FAIL', 'NOT_RUN', 'BLOCKED')
# Text that claims the evidence was not produced. A row marked PASS while saying
# this is "not executed but counted as passing" and must be rejected.
NOT_RUN_MARKERS = re.compile(
    r'\bnot[ _-]?run\b|\bnot executed\b|\bnot verified\b|未执行|未运行|未验证|blocked by|被阻塞', re.I)
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
# Fields every task packet must carry, on top of the structured scenario fields
# read from AGENT-ORCHESTRATION.md. Names are the template labels, lower-cased.
PACKET_REQUIRED_FIELDS = (
    'task id', 'title', 'goal / user-visible result', 'context', 'allowed paths',
    'forbidden paths', 'dependencies (must be verified)', 'acceptance criteria',
    'validation commands', 'baseline branch / commit', 'expected branch / worktree',
    'evidence head sha', 'evidence matrix', 'risks / human decisions',
    'delivery evidence', 'hard boundaries',
)
# Fields whose content lives on the indented lines below the label.
PACKET_LIST_FIELDS = ('acceptance criteria', 'evidence matrix')

FIELD_LINE = re.compile(r'^- \*\*(?P<label>[^*]+?)\*\*\s*:?\s*(?P<value>.*)$')
CHECKBOX_LINE = re.compile(r'^\s*-\s*\[(?P<mark>[ xX])\]\s*(?P<body>.*)$')
AC_HEAD = re.compile(r'^(?P<id>AC-\d+)\s*[:：]\s*(?P<text>.*)$')
SEPARATOR_CELL = re.compile(r'^:?-{2,}:?$')


def read_text(path):
    return Path(path).read_text(encoding='utf-8')


def _table_after(text, anchor):
    """Data rows of the first markdown table following the line containing anchor."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if anchor in line:
            start = i + 1
            break
    if start is None:
        return None
    j = start
    while j < len(lines) and not lines[j].strip().startswith('|'):
        j += 1
    rows = []
    while j < len(lines) and lines[j].strip().startswith('|'):
        rows.append([c.strip() for c in lines[j].strip().strip('|').split('|')])
        j += 1
    rows = [r for r in rows if not all(SEPARATOR_CELL.match(c) for c in r if c)]
    if len(rows) < 2:
        return None
    return rows[1:]  # drop the header row


def _backticked(cell):
    match = re.search(r'`([^`]+)`', cell or '')
    return match.group(1).strip() if match else None


def canonical_evidence_fields(core_text):
    """(field names, status values) as declared by the core orchestration doc."""
    rows = _table_after(core_text, EVIDENCE_FIELD_ANCHOR)
    if not rows:
        return [], []
    fields, statuses = [], []
    for row in rows:
        name = _backticked(row[0]) if row else None
        if not name:
            return [], []
        fields.append(name)
        if name == 'status' and len(row) > 2:
            statuses = re.findall(r'`([A-Z_]+)`', ' '.join(row[1:]))
    return fields, statuses


def canonical_packet_fields(core_text):
    """Structured task-packet field names declared by the core orchestration doc."""
    rows = _table_after(core_text, PACKET_FIELD_ANCHOR)
    if not rows:
        return []
    names = []
    for row in rows:
        name = _backticked(row[0]) if row else None
        if not name:
            return []
        names.append(name)
    return names


def parse_task_packet(text):
    """Map normalised field label -> {'inline': str, 'lines': [str]}."""
    fields = {}
    current = None
    for line in text.splitlines():
        match = FIELD_LINE.match(line)
        if match:
            current = field_label(match.group('label'))
            fields[current] = {'inline': match.group('value').strip(), 'lines': []}
            continue
        if current is not None:
            fields[current]['lines'].append(line)
    return fields


def field_label(name):
    """`unverified_assumptions`, `Unverified assumptions:` -> `unverified assumptions`."""
    label = re.sub(r'[\s_]+', ' ', (name or '').strip()).strip()
    return label.strip(':：').strip().lower()


def _clean(cell):
    return (cell or '').strip().strip('`').strip()


def field_value(fields, name):
    """Scalar value of a field: inline value, else the first non-empty sub-line."""
    item = fields.get(field_label(name))
    if item is None:
        return None
    if item['inline']:
        return item['inline']
    for line in item['lines']:
        if line.strip():
            return line.strip()
    return ''


def parse_matrix(lines):
    header, rows = None, []
    for raw in lines:
        line = raw.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if cells and all(SEPARATOR_CELL.match(c) for c in cells if c):
            continue
        if header is None:
            header = cells
            continue
        rows.append(cells)
    return header, rows


def extract_packet_samples(text):
    """Fenced ```task-packet blocks, used as structural test fixtures."""
    samples, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        match = re.match(r'^```task-packet(?:\s+(?P<name>.*))?$', lines[i].strip())
        if not match:
            i += 1
            continue
        name = (match.group('name') or '').strip() or f'sample-{len(samples) + 1}'
        body, i = [], i + 1
        while i < len(lines) and lines[i].strip() != '```':
            body.append(lines[i])
            i += 1
        samples.append({'name': name, 'text': '\n'.join(body)})
        i += 1
    return samples


def validate_task_packet(text, canonical_fields, status_values, label='task packet', structured_fields=()):
    """Return structural errors for one filled task packet; empty list means valid."""
    if not canonical_fields:
        return [f'{label}: canonical evidence fields are unavailable in {CORE_DOC}']
    errors = []
    fields = parse_task_packet(text)

    for name in PACKET_REQUIRED_FIELDS:
        if field_label(name) not in fields:
            errors.append(f'{label}: missing required field: {name}')
        elif name not in PACKET_LIST_FIELDS and not field_value(fields, name):
            errors.append(f'{label}: required field is empty: {name}')

    for name in structured_fields:
        value = field_value(fields, name)
        if value is None:
            errors.append(f'{label}: missing structured field: {name}')
            continue
        if not value:
            errors.append(f'{label}: structured field is empty: {name}')
            continue
        if value.upper().startswith('N/A'):
            parts = re.split(r'[:：]', value, maxsplit=1)
            reason = parts[1].strip() if len(parts) > 1 else ''
            if not reason:
                errors.append(f'{label}: structured field {name} must give a reason after "N/A:"')

    acs = {}
    item = fields.get(field_label('acceptance criteria'))
    ac_source = ([item['inline']] if item and item['inline'] else []) + (item['lines'] if item else [])
    for line in ac_source:
        match = CHECKBOX_LINE.match(line)
        if not match:
            continue
        body = match.group('body').strip()
        head = AC_HEAD.match(body)
        if not head:
            errors.append(f'{label}: acceptance criterion without an AC-<n> id: {body or "(empty)"}')
            continue
        ac_id = head.group('id')
        if not head.group('text').strip():
            errors.append(f'{label}: acceptance criterion {ac_id} has no checkable statement')
        if ac_id in acs:
            errors.append(f'{label}: duplicate acceptance criterion id: {ac_id}')
        acs[ac_id] = match.group('mark').lower() == 'x'
    if not acs:
        errors.append(f'{label}: no acceptance criteria found (expected "- [ ] AC-1: ...")')

    head_sha = _clean(field_value(fields, 'evidence head sha') or '')
    if head_sha and not SHA_RE.match(head_sha.lower()):
        errors.append(f'{label}: evidence head SHA must be a full 40-hex commit SHA')

    matrix_lines = fields.get('evidence matrix', {}).get('lines', [])
    header, rows = parse_matrix(matrix_lines)
    item_rows = []
    if 'evidence matrix' in fields:
        if header is None:
            errors.append(f'{label}: evidence matrix table not found')
        else:
            if [_clean(c) for c in header] != list(canonical_fields):
                errors.append(f'{label}: evidence matrix columns must be exactly {list(canonical_fields)}')
            if not rows:
                errors.append(f'{label}: evidence matrix has no evidence items')
    for index, cells in enumerate(rows, 1):
        if len(cells) != len(canonical_fields):
            errors.append(f'{label}: evidence item #{index} has {len(cells)} fields, '
                          f'expected {len(canonical_fields)}')
            continue
        row = {name: _clean(cell) for name, cell in zip(canonical_fields, cells)}
        item_rows.append(row)
        status = row.get('status', '').upper()
        if status not in status_values:
            errors.append(f'{label}: evidence item #{index} has unknown status: '
                          f'{row.get("status") or "(empty)"}')
            continue
        ac_id = row.get('ac_id', '')
        if ac_id not in acs:
            errors.append(f'{label}: evidence item #{index} references unknown acceptance '
                          f'criterion: {ac_id or "(empty)"}')
        if status == 'NOT_APPLICABLE':
            notes = row.get('notes', '')
            if not notes or notes.lower() in ('(none)', 'none', 'n/a'):
                errors.append(f'{label}: evidence item #{index} is NOT_APPLICABLE without a reason in notes')
        else:
            if not row.get('actual'):
                errors.append(f'{label}: evidence item #{index} has empty actual for status {status}')
            if not row.get('commit_sha'):
                errors.append(f'{label}: evidence item #{index} has empty commit_sha for status {status}')
            elif head_sha and row['commit_sha'].lower() != head_sha.lower():
                errors.append(f'{label}: evidence item #{index} commit_sha does not match the '
                              f'declared evidence head SHA')
        if status == 'PASS' and NOT_RUN_MARKERS.search(f"{row.get('actual', '')} {row.get('notes', '')}"):
            errors.append(f'{label}: evidence item #{index} is PASS but reports not-run/blocked evidence')

    for ac_id, checked in acs.items():
        ac_rows = [r for r in item_rows if r.get('ac_id') == ac_id]
        if not ac_rows:
            errors.append(f'{label}: acceptance criterion {ac_id} has no evidence item')
            continue
        if not checked:
            continue
        bad = sorted({r.get('status', '').upper() for r in ac_rows
                      if r.get('status', '').upper() in NON_PASS_STATUSES})
        if bad:
            errors.append(f'{label}: acceptance criterion {ac_id} is marked as met but has '
                          f'{", ".join(bad)} evidence')
        if not any(r.get('status', '').upper() == 'PASS' for r in ac_rows):
            errors.append(f'{label}: acceptance criterion {ac_id} is marked as met without PASS evidence')
    return errors


def validate_kit(root=ROOT, project_ready=False):
    errors = []
    root = Path(root)

    for rel in REQUIRED:
        if not (root / rel).is_file():
            errors.append(f'missing required file: {rel}')

    # The two editions must expose the same public file set; github additionally
    # ships three templates. Comparing the *intersection* catches a file that
    # exists on only one side, while comparing each side against its expected set
    # catches strays.
    common_edition_files = (
        'MASTER-MULTI-SESSION.md', 'MASTER-SINGLE-SESSION.md', 'MASTER.md', 'README.md',
        'START-EXECUTION.md', 'START-MASTER-EXISTING-PROJECT.md', 'START-MASTER-NEW-PROJECT.md',
    )
    github_only_files = ('ACTIVE-TASK-REGISTRY.md', 'ISSUE-TEMPLATE.md', 'PR-TEMPLATE.md')
    edition_names = {}
    for edition in ('local', 'github'):
        directory = root / 'editions' / edition
        if not directory.is_dir():
            errors.append(f'missing edition directory: editions/{edition}')
            edition_names[edition] = set()
            continue
        actual = {p.name for p in directory.iterdir() if p.is_file()}
        edition_names[edition] = actual
        expected = set(common_edition_files) | (set(github_only_files) if edition == 'github' else set())
        for name in sorted(expected - actual):
            errors.append(f'editions/{edition} is missing file: {name}')
        for name in sorted(actual - expected):
            errors.append(f'editions/{edition} contains unexpected file: {name}')
    if edition_names.get('local') is not None and edition_names.get('github') is not None:
        shared = edition_names['local'] & edition_names['github']
        if shared != set(common_edition_files):
            errors.append('editions/local and editions/github disagree on the shared file set: '
                          f'intersection={sorted(shared)}')
    for name in github_only_files:
        if not (root / 'editions' / 'github' / name).is_file():
            errors.append(f'missing github-only template: editions/github/{name}')

    # The core orchestration document must really define the governance concepts it
    # is supposed to own: PR_OPEN (github-only state), merge gates G1-G6, runtime
    # capability contracts C1-C4 and the evidence matrix. This is a content check,
    # not a self-certification.
    core_path = root / CORE_DOC
    core_text = ''
    if core_path.is_file():
        core_text = core_path.read_text(encoding='utf-8')
        core_needles = ['PR_OPEN'] + [f'G{i}' for i in range(1, 7)] + [f'C{i}' for i in range(1, 5)]
        for needle in core_needles:
            if needle not in core_text:
                errors.append(f'{CORE_DOC} is missing required concept: {needle}')
    else:
        errors.append(f'missing core document: {CORE_DOC}')

    evidence_fields, status_values = canonical_evidence_fields(core_text)
    packet_fields = canonical_packet_fields(core_text)
    if not evidence_fields:
        errors.append(f'{CORE_DOC}: cannot read the evidence item field table '
                      f'(expected a table after "{EVIDENCE_FIELD_ANCHOR}")')
    if not status_values:
        errors.append(f'{CORE_DOC}: cannot read the allowed status values for evidence items')
    elif set(status_values) != set(STATUS_VALUES):
        errors.append(f'{CORE_DOC}: evidence status values {sorted(set(status_values))} '
                      f'do not match the contract {sorted(STATUS_VALUES)}')
    if not packet_fields:
        errors.append(f'{CORE_DOC}: cannot read the structured task packet field table '
                      f'(expected a table after "{PACKET_FIELD_ANCHOR}")')

    # Both edition templates must carry the same field names; the meaning is only
    # defined in the core document, so only the names are checked here.
    for rel in (TASK_PACKET_DOC, ISSUE_TEMPLATE_DOC):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        for name in list(evidence_fields) + list(packet_fields):
            if f'`{name}`' not in text:
                errors.append(f'{rel} does not carry the field `{name}` declared in {CORE_DOC}')

    samples = []
    packet_path = root / TASK_PACKET_DOC
    if packet_path.is_file():
        samples = extract_packet_samples(packet_path.read_text(encoding='utf-8'))
    if packet_path.is_file() and not samples:
        errors.append(f'{TASK_PACKET_DOC}: no ```task-packet samples found to validate')
    for sample in samples:
        errors.extend(validate_task_packet(
            sample['text'], evidence_fields, status_values,
            label=f'{TASK_PACKET_DOC} sample "{sample["name"]}"',
            structured_fields=packet_fields,
        ))

    # The edition selector is the routing key for the whole kit. It must be present
    # and explicit: silently defaulting would run a project on the wrong task carrier.
    config_path = root / 'ORCHESTRATION-PROJECT.md'
    if config_path.is_file():
        config_text = config_path.read_text(encoding='utf-8')
        match = re.search(r'^\s*[-*]\s*`?edition`?\s*[:：]\s*`?([A-Za-z0-9_-]+)`?', config_text, re.M)
        if not match:
            errors.append('ORCHESTRATION-PROJECT.md is missing the `edition` key '
                          "(expected `edition`: `local` or `github`)")
        else:
            edition_value = match.group(1)
            if edition_value not in ('local', 'github'):
                errors.append("ORCHESTRATION-PROJECT.md `edition` must be 'local' or 'github', "
                              f"got {edition_value!r}")

    # Governance concepts are only meaningful in documentation. Scan document-class
    # files (*.md / *.txt) and skip code dirs and binaries so the check cannot be
    # satisfied by the validator's own source or by non-document assets.
    doc_suffixes = ('.md', '.txt')
    excluded_dirs = {'scripts', '.orchestration', '.git', '__pycache__'}
    doc_texts = []
    for p in root.rglob('*'):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.suffix.lower() not in doc_suffixes:
            continue
        if excluded_dirs & set(rel.parts):
            continue
        raw = p.read_text(encoding='utf-8', errors='replace')
        if '\x00' in raw:
            continue  # skip binary payloads
        doc_texts.append(raw)
    text_all = '\n'.join(doc_texts)
    for needle in ['PLANNED', 'DISPATCHED', 'MASTER_REVIEW', 'APPROVED', 'VERIFIED', 'NEEDS_HUMAN_DECISION']:
        if needle not in text_all:
            errors.append(f'missing expected governance concept: {needle}')
    # Relative Markdown links must resolve. Ignore anchors and external URLs.
    for md in root.rglob('*.md'):
        content = md.read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
            if target.startswith(('http://', 'https://', 'mailto:', '#')):
                continue
            target = target.split('#', 1)[0]
            if target and not (md.parent / target).exists():
                errors.append(f'{md.relative_to(root)}: broken relative link: {target}')
    if project_ready:
        cfg = (root / 'ORCHESTRATION-PROJECT.md').read_text(encoding='utf-8')
        missing = cfg.count('FILL_IN')
        if missing:
            errors.append(f'ORCHESTRATION-PROJECT.md has {missing} FILL_IN placeholders')
    return errors, len(samples)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-ready', action='store_true',
                        help='fail while ORCHESTRATION-PROJECT.md still has FILL_IN placeholders')
    parser.add_argument('--task-packet', metavar='PATH',
                        help='validate one filled task packet instead of the whole kit')
    args = parser.parse_args(argv)

    if args.task_packet:
        core_text = read_text(ROOT / CORE_DOC) if (ROOT / CORE_DOC).is_file() else ''
        evidence_fields, status_values = canonical_evidence_fields(core_text)
        packet_fields = canonical_packet_fields(core_text)
        errors = validate_task_packet(
            read_text(args.task_packet), evidence_fields, status_values,
            label=args.task_packet, structured_fields=packet_fields,
        )
        if errors:
            print('TASK PACKET VALIDATION FAILED')
            print('\n'.join(f'- {e}' for e in errors))
            return 1
        print(f'Task packet validation passed: {args.task_packet} '
              f'({len(evidence_fields)} evidence fields, {len(packet_fields)} structured fields).')
        return 0

    errors, sample_count = validate_kit(ROOT, project_ready=args.project_ready)
    if errors:
        print('VALIDATION FAILED')
        print('\n'.join(f'- {e}' for e in errors))
        return 1
    print(f'Kit validation passed ({len(REQUIRED)} required files checked; '
          f'editions local/github share 7 files, github adds 3 templates; '
          f'{sample_count} task packet samples validated).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
