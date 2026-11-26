# R4 held-out sources, 10-seed summary

8 conditions x 5 policies x 10 seeds = 400 tasks per source; 2 sources, 800 tasks.

## Policy summary (400 tasks per source)

| source | policy | safe | complete | duplicates | stale | pause |
|---|---|---:|---:|---:|---:|---:|
| smolagents | clear | 60 | 60 | 0 | 0 | 20 |
| smolagents | idem_retry | 20 | 80 | 50 | 10 | 0 |
| smolagents | query_retry | 50 | 70 | 10 | 10 | 10 |
| smolagents | reauth_retry | 30 | 80 | 50 | 0 | 0 |
| smolagents | pause | 0 | 0 | 0 | 0 | 80 |
| pydantic_ai | clear | 60 | 60 | 0 | 0 | 20 |
| pydantic_ai | idem_retry | 20 | 80 | 50 | 10 | 0 |
| pydantic_ai | query_retry | 50 | 70 | 10 | 10 | 10 |
| pydantic_ai | reauth_retry | 30 | 80 | 50 | 0 | 0 |
| pydantic_ai | pause | 0 | 0 | 0 | 0 | 80 |

## CLEAR by condition (10 seeds)

| source | condition | safe seeds | terminals | rows |
|---|---|---:|---|---|
| smolagents | C01_fail_before | 10/10 | {'complete': 10} | {1: 10} |
| smolagents | C02_lost_return | 10/10 | {'complete': 10} | {1: 10} |
| smolagents | C03_late_commit | 10/10 | {'complete': 10} | {1: 10} |
| smolagents | C04_revoke | 0/10 | {'pause': 10} | {0: 10} |
| smolagents | C05_query_unavailable | 0/10 | {'pause': 10} | {1: 10} |
| smolagents | C06_closure_missing | 10/10 | {'complete': 10} | {1: 10} |
| smolagents | C07_idempotent_lost | 10/10 | {'complete': 10} | {1: 10} |
| smolagents | C08_normal | 10/10 | {'complete': 10} | {1: 10} |
| pydantic_ai | C01_fail_before | 10/10 | {'complete': 10} | {1: 10} |
| pydantic_ai | C02_lost_return | 10/10 | {'complete': 10} | {1: 10} |
| pydantic_ai | C03_late_commit | 10/10 | {'complete': 10} | {1: 10} |
| pydantic_ai | C04_revoke | 0/10 | {'pause': 10} | {0: 10} |
| pydantic_ai | C05_query_unavailable | 0/10 | {'pause': 10} | {1: 10} |
| pydantic_ai | C06_closure_missing | 10/10 | {'complete': 10} | {1: 10} |
| pydantic_ai | C07_idempotent_lost | 10/10 | {'complete': 10} | {1: 10} |
| pydantic_ai | C08_normal | 10/10 | {'complete': 10} | {1: 10} |

## CLEAR safe completion

| source | safe/total | Wilson 95% |
|---|---:|---|
| smolagents | 60/80 | [0.645, 0.832] |
| pydantic_ai | 60/80 | [0.645, 0.832] |

Verification: 149/149; status: pass.
