"""Create auditable new baseline workers from immutable H02/H03/H04 adapters.

No original file is edited. Replacements are deliberately limited to observers,
baseline branches and explicit idempotency opt-in. Not a target execution.
"""
from pathlib import Path
import hashlib, json
ROOT = Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def frozen(stage, name):
    p = ROOT / 'scripts' / name
    protocol = json.loads((ROOT / 'runs' / stage / 'attempt1/protocol.json').read_text(encoding='utf-8'))
    assert sha(p) == protocol['scripts'][name]
    return p.read_text(encoding='utf-8')
def replace(s, old, new):
    assert s.count(old) == 1, old[:100]
    return s.replace(old, new)
def write(name, s):
    p = ROOT / 'scripts' / name
    assert not p.exists()
    p.write_text(s, encoding='utf-8')
    print(name)

s = frozen('H02', 'h02_worker.py')
s = replace(s, "state_result = path.read_bytes().hex() if native else state['data'].hex()",
    "state_result = (path.read_bytes().hex() if native else state['data'].hex()) if (not native or oracle or 'final_state' in channels) else None")
s = replace(s, "state_result = backing.snapshot()", "state_result = backing.snapshot() if (not native or oracle or 'final_state' in channels) else None")
s = replace(s, "if not native: row['model_state'] = state_result", "if not native: row['model_state'] = state_result\n    if 'final_state' in channels: row['final_state'] = state_result")
s = replace(s, "(ROOT / 'runs/H02').resolve()", "(ROOT / 'runs').resolve()")
write('rb01_local_worker.py', s)

s = frozen('H03', 'h03_client.py')
s = replace(s, "choices=['spg', 'adaptive_sql', 'fixed_full', 'io_only']", "choices=['spg', 'fixed_full', 'io_only', 'return_only']")
s = replace(s, "if a.method == 'io_only':\n", "if a.method == 'return_only':\n            label, reason = 'unknown', 'return_does_not_establish_prior_authorization_or_effect_completeness'\n        elif a.method == 'io_only':\n")
write('rb01_h03_client.py', s)

s = frozen('H04', 'h04_client.py')
s = replace(s, "p.add_argument('--base-url', required=True); p.add_argument('--method', required=True)",
    "p.add_argument('--base-url', required=True); p.add_argument('--method', required=True, choices=['spg','retry_only','idempotency_only','query_only','reauthorize_only','pause'])")
s = replace(s, "if action == 'retry' or action == 'initial_append': body['permit'] = permit",
    "if action == 'retry' or action == 'initial_append':\n                    body['permit'] = permit\n                    body['use_idempotency'] = caps['idempotency'] and a.method in ['spg', 'idempotency_only']")
s = replace(s, "calls.append(dict(action=action, recovery=recovery, **result))",
    "calls.append(dict(action=action, recovery=recovery, dedup_requested=(caps['idempotency'] and a.method in ['spg', 'idempotency_only']) if action in ['retry','initial_append'] else None, permit_epoch=permit['epoch'] if action in ['retry','initial_append'] else None, **result))")
start = s.index("        elif a.method == 'sdk_retry':")
end = s.index("        results.append(", start)
s = s[:start] + '''        elif a.method == 'retry_only':
            response = request('retry')
            terminal = 'complete' if committed(response) else 'paused'; reason = 'one_retry_original_permit_no_dedup'
        elif a.method == 'idempotency_only':
            if caps['idempotency']:
                response = request('retry')
                terminal = 'complete' if committed(response) else 'paused'; reason = 'same_idempotency_key_original_permit'
            else: reason = 'idempotency_not_supported'
        elif a.method == 'query_only':
            if caps['query']:
                state = query_state(request('query'))
                if state == 'committed': terminal, reason = 'complete', 'query_committed'
                elif state == 'not_committed':
                    response = request('retry')
                    terminal = 'complete' if committed(response) else 'paused'; reason = 'query_negative_retry_original_permit_no_dedup'
                else: reason = 'query_unavailable'
            else: reason = 'query_not_supported'
        elif a.method == 'reauthorize_only':
            response = request('authorize'); permit = response['body']['permit']
            if permit['allowed']:
                response = request('retry')
                terminal = 'complete' if committed(response) else 'paused'; reason = 'fresh_permit_retry_no_query_no_dedup'
            else: reason = 'permission_denied_prior_commit_unknown'
        elif a.method != 'pause': raise ValueError('unknown method')
''' + s[end:]
assert 'capability_script' not in s and 'idempotent_reauth' not in s and 'query_reauth' not in s
write('rb01_h04_client.py', s)

s = frozen('H04', 'h04_service.py')
s = replace(s, "if cfg['idempotency'] and previous:", "if cfg['idempotency'] and req.get('use_idempotency', False) and previous:")
s = replace(s, "dict(kind='append_attempt', permit=permit, actual_epoch=rec['epoch'], actual_allowed=rec['allowed'])",
    "dict(kind='append_attempt', permit=permit, actual_epoch=rec['epoch'], actual_allowed=rec['allowed'], dedup_requested=req.get('use_idempotency', False))")
write('rb01_h04_service.py', s)
