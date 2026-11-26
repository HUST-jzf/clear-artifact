# R14 extended held-out sources, 10-seed summary

8 conditions x 5 policies x 10 seeds = 400 tasks per source; 2 sources, 800 tasks.

## Policy summary (400 tasks per source)

| source | policy | safe | complete | duplicates | stale | pause |
|---|---|---:|---:|---:|---:|---:|
| llamaindex | clear | 60 | 60 | 0 | 0 | 20 |
| llamaindex | idem_retry | 20 | 80 | 50 | 10 | 0 |
| llamaindex | query_retry | 50 | 70 | 10 | 10 | 10 |
| llamaindex | reauth_retry | 30 | 80 | 50 | 0 | 0 |
| llamaindex | pause | 0 | 0 | 0 | 0 | 80 |
| autogen | clear | 60 | 60 | 0 | 0 | 20 |
| autogen | idem_retry | 20 | 80 | 50 | 10 | 0 |
| autogen | query_retry | 50 | 70 | 10 | 10 | 10 |
| autogen | reauth_retry | 30 | 80 | 50 | 0 | 0 |
| autogen | pause | 0 | 0 | 0 | 0 | 80 |

## CLEAR by condition (10 seeds)

| source | condition | safe seeds | terminals | rows |
|---|---|---:|---|---|
| llamaindex | C01_fail_before | 10/10 | {'complete': 10} | {1: 10} |
| llamaindex | C02_lost_return | 10/10 | {'complete': 10} | {1: 10} |
| llamaindex | C03_late_commit | 10/10 | {'complete': 10} | {1: 10} |
| llamaindex | C04_revoke | 0/10 | {'pause': 10} | {0: 10} |
| llamaindex | C05_query_unavailable | 0/10 | {'pause': 10} | {1: 10} |
| llamaindex | C06_closure_missing | 10/10 | {'complete': 10} | {1: 10} |
| llamaindex | C07_idempotent_lost | 10/10 | {'complete': 10} | {1: 10} |
| llamaindex | C08_normal | 10/10 | {'complete': 10} | {1: 10} |
| autogen | C01_fail_before | 10/10 | {'complete': 10} | {1: 10} |
| autogen | C02_lost_return | 10/10 | {'complete': 10} | {1: 10} |
| autogen | C03_late_commit | 10/10 | {'complete': 10} | {1: 10} |
| autogen | C04_revoke | 0/10 | {'pause': 10} | {0: 10} |
| autogen | C05_query_unavailable | 0/10 | {'pause': 10} | {1: 10} |
| autogen | C06_closure_missing | 10/10 | {'complete': 10} | {1: 10} |
| autogen | C07_idempotent_lost | 10/10 | {'complete': 10} | {1: 10} |
| autogen | C08_normal | 10/10 | {'complete': 10} | {1: 10} |

## CLEAR safe completion

| source | safe/total | Wilson 95% |
|---|---:|---|
| llamaindex | 60/80 | [0.645, 0.832] |
| autogen | 60/80 | [0.645, 0.832] |

Verification: 149/149; status: pass.
