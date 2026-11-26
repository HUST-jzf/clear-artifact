"""R9 usability audit: integration surface, evidence shims, friction, frozen limits."""
import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    dict(source='mcp', path='scripts/r1_native.py', cls='Host'),
    dict(source='anyio', path='scripts/r1_anyio.py', cls='Host'),
    dict(source='langchain', path='scripts/r1_langchain.py', cls='Host'),
    dict(source='smolagents', path='scripts/r4_holdout.py', cls='SmolagentsAdapter'),
    dict(source='pydantic_ai', path='scripts/r4_holdout.py', cls='PydanticAIAdapter'),
]
HOST_SHIMS = ['describe', 'effects', 'status', 'reauthorize', 'drain']
# Files that actually carry evidence operations for each source. LangChain reuses
# the AnyIO Host; smolagents/Pydantic AI reuse r4_holdout.Host's call dispatch,
# so counting methods on each adapter class alone is not enough.
SHIM_SOURCES = {
    'mcp': ['scripts/r1_native.py', 'scripts/r1_server.py'],
    'anyio': ['scripts/r1_anyio.py'],
    'langchain': ['scripts/r1_anyio.py', 'scripts/r1_langchain.py'],
    'smolagents': ['scripts/r4_holdout.py'],
    'pydantic_ai': ['scripts/r4_holdout.py'],
}
CONFIG_FIELDS = ['revision', 'schema', 'mode', 'outcome', 'delayed', 'abandon_on_cancel',
                 'delegated', 'closed_registration', 'allowed', 'store', 'idempotency',
                 'query_complete']
NATIVE = {name: dict(effects_query=False, lifecycle_registry=False, version_binding=False,
                     atomic_admission=False)
          for name in ['mcp', 'anyio', 'langchain', 'smolagents', 'pydantic_ai']}
RUNS = [
    ('R2_mcp', 'attempt1', 500), ('R2_anyio', 'attempt1', 500),
    ('R2_langchain', 'attempt2', 500), ('R4_smolagents', 'attempt1', 40),
    ('R4_pydantic_ai', 'attempt1', 40), ('R7', 'attempt2', 1200),
    ('R8', 'attempt3', 450),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def class_source(path, name):
    text = Path(path).read_text(encoding='utf-8')
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node, '\n'.join(text.splitlines()[node.lineno - 1:node.end_lineno])
    raise KeyError(f'{name} not in {path}')


def shims_present(paths):
    """Return documented evidence operations that appear as string literals."""
    found = set()
    for path in paths:
        tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in HOST_SHIMS:
                    found.add(node.value)
    return [name for name in HOST_SHIMS if name in found]


def frozen_check():
    results = []
    for directory, attempt, expected in RUNS:
        run = ROOT / 'runs' / directory / attempt
        completion = json.loads((run / 'completion.json').read_text(encoding='utf-8'))
        count = len(completion['tasks'])
        results.append(dict(run=f'{directory}/{attempt}', tasks=count,
                            expected=expected, ok=count == expected))
    run = ROOT / 'runs/R8/attempt3'
    freeze = json.loads((run / 'freeze.json').read_text(encoding='utf-8'))
    hashes_ok = all((run / 'snapshots' / name).exists() and
                    sha(run / 'snapshots' / name) == expected
                    for name, expected in freeze['files'].items())
    results.append(dict(run='R8/attempt3 snapshots', tasks=None, expected=None,
                        ok=hashes_ok))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='runs/R9/attempt1')
    args = parser.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    issues = json.loads((out / 'issues.json').read_text(encoding='utf-8'))
    rows = []
    for item in SOURCES:
        node, source = class_source(ROOT / item['path'], item['cls'])
        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        branches = len(re.findall(r'\bC0[1-9]\b|case\s*==|condition\s*==|mode\s*==', source))
        source_issues = [i for i in issues if i['source'] == item['source']]
        rows.append(dict(source=item['source'], path=item['path'], cls=item['cls'],
                         loc=node.end_lineno - node.lineno + 1, methods=methods,
                         method_count=len(methods), per_condition_branches=branches,
                         shims=shims_present(SHIM_SOURCES[item['source']]),
                         native=NATIVE[item['source']], issues=len(source_issues),
                         unresolved=sum(1 for i in source_issues if i['status'] != 'resolved')))
    shared_paths = ['scripts/r1_policies.py', 'src/clear_assurance/core.py']
    shared_loc = sum(len(Path(ROOT / path).read_text(encoding='utf-8').splitlines())
                     for path in shared_paths)
    categories = Counter(i['category'] for i in issues)
    frozen = frozen_check()
    acceptance = dict(
        zero_condition_branches=all(row['per_condition_branches'] == 0 for row in rows),
        shims_documented=all(set(HOST_SHIMS) <= set(row['shims']) for row in rows),
        no_unresolved=all(i['status'] == 'resolved' for i in issues),
        frozen_unchanged=all(item['ok'] for item in frozen))
    audit = dict(schema='r9_audit_v1', sources=rows, host_shims=HOST_SHIMS,
                 config_field_count=len(CONFIG_FIELDS), config_fields=CONFIG_FIELDS,
                 shared_control=dict(paths=shared_paths, loc=shared_loc),
                 total_adapter_loc=sum(row['loc'] for row in rows),
                 issues=dict(total=len(issues), by_category=dict(categories),
                             unresolved=sum(1 for i in issues if i['status'] != 'resolved')),
                 frozen=frozen, acceptance=acceptance)
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n',
                                    encoding='utf-8')
    lines = ['| source | adapter class | adapter LOC | methods | per-condition branches | native effects/lifecycle | issues |',
             '|---|---|---:|---:|---:|---|---:|']
    for row in rows:
        lines.append('| {} | `{}` | {} | {} | {} | no / no | {} |'.format(
            row['source'], row['cls'], row['loc'], row['method_count'],
            row['per_condition_branches'], row['issues']))
    lines.append('')
    lines.append('Host shims: ' + ', '.join(f'`{name}`' for name in HOST_SHIMS))
    lines.append('Host shim coverage: ' + ', '.join(
        f"{row['source']} {len(row['shims'])}/5" for row in rows))
    lines.append('')
    lines.append('Config fields: {}; shared control LOC: {}; total adapter LOC: {}'.format(
        len(CONFIG_FIELDS), shared_loc, audit['total_adapter_loc']))
    lines.append('')
    lines.append('Issues: {} total, {} unresolved; categories: {}'.format(
        len(issues), audit['issues']['unresolved'], dict(categories)))
    lines.append('')
    lines.append('Acceptance: ' + json.dumps(acceptance, ensure_ascii=False))
    (out / 'table.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(sources=rows, config_field_count=len(CONFIG_FIELDS),
                          shared_control_loc=shared_loc, issues=audit['issues'],
                          frozen=frozen, acceptance=acceptance), ensure_ascii=False))


if __name__ == '__main__':
    main()
