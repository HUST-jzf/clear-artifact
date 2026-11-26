"""R41: bounded concurrent model check for T5 (end-to-end) and T6 (fence settlement)."""
import argparse
import json
from pathlib import Path

T5_DEPTH = 8
T6_DEPTH = 6


def read(committed):
    return not committed


def explore_t5(config, depth=T5_DEPTH):
    """Two controllers, legacy write path. State: committed, seen_empty, lease."""
    start = (frozenset(), (False, False), None)
    actions = [('read', 0), ('read', 1), ('write', 0), ('write', 1),
               ('crash', 0), ('crash', 1), ('lease', 0), ('lease', 1)]
    frontier = [(start, [])]
    seen = {start}
    for _ in range(depth):
        following = []
        for state, trace in frontier:
            committed, checked, lease = state
            for action in actions:
                kind, c = action
                if kind == 'read':
                    if config['single_writer'] and lease != c:
                        continue
                    nxt = (committed,
                           tuple(read(committed) if i == c else value
                                 for i, value in enumerate(checked)), lease)
                elif kind == 'lease':
                    if config['single_writer'] and lease not in (None, c):
                        continue
                    nxt = (committed, checked, c)
                elif kind == 'write':
                    if not checked[c]:
                        continue
                    if config['single_writer'] and lease != c:
                        continue
                    if config['atomic_admit'] and committed:
                        continue
                    nxt = (committed | {c + 1},
                           tuple(False if i == c else value
                                 for i, value in enumerate(checked)),
                           lease)
                else:  # crash: local knowledge and lease are lost
                    nxt = (committed,
                           tuple(False if i == c else value
                                 for i, value in enumerate(checked)),
                           None if lease == c else lease)
                if len(nxt[0]) >= 2:
                    return dict(duplicate_reachable=True, trace=trace + [list(action)])
                if nxt not in seen:
                    seen.add(nxt)
                    following.append((nxt, trace + [list(action)]))
        frontier = following
    return dict(duplicate_reachable=False, trace=None)


def explore_t6(config, depth=T6_DEPTH):
    """Two controllers, fence settlement skeleton. State: committed, provisional,
    finalized, next_f, original_done. Fence 1 belongs to the original request."""
    start = (frozenset(), frozenset(), 0, 2, False)
    actions = [('original',), ('stage', 0), ('stage', 1), ('finalize', 0),
               ('finalize', 1), ('abort', 0), ('abort', 1)]
    staged = [0, 0]
    frontier = [((start, tuple(staged)), [])]
    seen = {(start, tuple(staged))}
    for _ in range(depth):
        following = []
        for (state, staged), trace in frontier:
            committed, provisional, finalized, next_f, done = state
            for action in actions:
                kind = action[0]
                c = action[1] if len(action) > 1 else None
                nxt_staged = list(staged)
                if kind == 'original':
                    if done:
                        continue
                    if config['enforce'] and 1 <= finalized:
                        nxt = (committed, provisional, finalized, next_f, True)
                    else:
                        nxt = (committed | {1}, provisional,
                               1 if config['enforce'] else finalized, next_f, True)
                elif kind == 'stage':
                    f = next_f
                    if f <= finalized:
                        continue
                    nxt_staged[c] = f
                    nxt = (committed, provisional | {f}, finalized, next_f + 1, done)
                elif kind == 'finalize':
                    f = staged[c]
                    if not f or f not in provisional:
                        continue
                    if config['finalize_check'] and committed:
                        continue
                    if config['enforce'] and f <= finalized:
                        continue
                    nxt_staged[c] = 0
                    nxt = (committed | {f}, provisional - {f},
                           f if config['enforce'] else finalized, next_f, done)
                else:  # abort
                    f = staged[c]
                    if not f or f not in provisional:
                        continue
                    nxt_staged[c] = 0
                    nxt = (committed, provisional - {f}, finalized, next_f, done)
                if len(nxt[0]) >= 2:
                    return dict(duplicate_reachable=True, trace=trace + [list(action)])
                key = (nxt, tuple(nxt_staged))
                if key not in seen:
                    seen.add(key)
                    following.append((key, trace + [list(action)]))
        frontier = following
    return dict(duplicate_reachable=False, trace=None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    t5 = {'t5_no_a6': dict(single_writer=False, atomic_admit=False),
          't5_lease': dict(single_writer=True, atomic_admit=False),
          't5_atomic_admit': dict(single_writer=False, atomic_admit=True)}
    t6 = {'t6_both': dict(enforce=True, finalize_check=True),
          't6_fence_only': dict(enforce=True, finalize_check=False),
          't6_finalize_only': dict(enforce=False, finalize_check=True),
          't6_neither': dict(enforce=False, finalize_check=False)}
    expected = {'t5_no_a6': True, 't5_lease': False, 't5_atomic_admit': False,
                't6_both': False, 't6_fence_only': True, 't6_finalize_only': True,
                't6_neither': True}
    report = dict(t5_depth=T5_DEPTH, t6_depth=T6_DEPTH, controllers=2, configs={})
    for name, config in t5.items():
        result = explore_t5(config)
        report['configs'][name] = dict(model='t5', assumptions=config,
                                       expected=expected[name], **result)
    for name, config in t6.items():
        result = explore_t6(config)
        report['configs'][name] = dict(model='t6', assumptions=config,
                                       expected=expected[name], **result)
    report['passed'] = all(cell['duplicate_reachable'] == cell['expected']
                           for cell in report['configs'].values())
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({name: cell['duplicate_reachable']
                      for name, cell in report['configs'].items()}))
    print(json.dumps(dict(passed=report['passed'])))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
