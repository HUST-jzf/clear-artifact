"""Bounded exhaustive check of the fence-settlement skeleton (T6)."""
import argparse
import itertools
import json

CONFIGS = [('both', True, True), ('fence_only', True, False),
           ('finalize_only', False, True), ('neither', False, False)]
ACTIONS = [('late', 1), ('stage', 2), ('finalize', 2), ('abort', 2)]


def step(state, action, enforce, check):
    committed, provisional, finalized = state
    kind, fence = action
    if kind == 'late':
        if enforce and fence <= finalized:
            return None
        return (committed | {fence}, provisional,
                max(finalized, fence) if enforce else finalized)
    if kind == 'stage':
        if enforce and fence <= finalized:
            return None
        return (committed, provisional | {fence}, finalized)
    if kind == 'finalize':
        if fence not in provisional:
            return None
        if check and committed:
            return None
        if enforce and fence <= finalized:
            return None
        return (committed | {fence}, provisional - {fence},
                max(finalized, fence) if enforce else finalized)
    if kind == 'abort':
        if fence not in provisional:
            return None
        return (committed, provisional - {fence}, finalized)
    return None


def explore(enforce, check, depth=5):
    start = (frozenset(), frozenset(), 0)
    frontier = [(start, [])]
    seen = {start}
    for _ in range(depth):
        following = []
        for state, trace in frontier:
            for action in ACTIONS:
                nxt = step(state, action, enforce, check)
                if nxt is None:
                    continue
                if len(nxt[0]) >= 2:
                    return dict(duplicate_reachable=True, trace=trace + [action],
                                committed=sorted(nxt[0]))
                if nxt not in seen:
                    seen.add(nxt)
                    following.append((nxt, trace + [action]))
        frontier = following
    return dict(duplicate_reachable=False, trace=None, committed=None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    report = {'depth': 5,
              'actions': [[kind, fence] for kind, fence in ACTIONS],
              'configs': {}}
    for name, enforce, check in CONFIGS:
        report['configs'][name] = dict(enforce_fence=enforce, finalize_check=check,
                                       **explore(enforce, check))
    with open(args.out, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({name: cell['duplicate_reachable']
                      for name, cell in report['configs'].items()}))


if __name__ == '__main__':
    main()
