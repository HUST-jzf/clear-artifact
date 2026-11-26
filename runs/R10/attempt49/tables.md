# R10 reproduced tables

## R1 (7,200 tasks)

| source | policy | safe | duplicate | stale |
|---|---|---:|---:|---:|
| mcp | clear | 224 | 0 | 0 |
| mcp | idem_retry | 160 | 160 | 240 |
| mcp | query_retry | 149 | 37 | 72 |
| mcp | reauth_retry | 318 | 160 | 0 |
| mcp | pause | 0 | 0 | 0 |
| anyio | clear | 220 | 0 | 0 |
| anyio | idem_retry | 160 | 160 | 240 |
| anyio | query_retry | 140 | 40 | 80 |
| anyio | reauth_retry | 320 | 160 | 0 |
| anyio | pause | 0 | 0 | 0 |
| langchain | clear | 220 | 0 | 0 |
| langchain | idem_retry | 160 | 160 | 240 |
| langchain | query_retry | 140 | 40 | 80 |
| langchain | reauth_retry | 320 | 160 | 0 |
| langchain | pause | 0 | 0 | 0 |

## R2 (1,500 tasks)

| source | safe | complete | duplicate | stale | pause | pause with effect | CLEAR safe |
|---|---:|---:|---:|---:|---:|---:|---:|
| mcp | 200 | 380 | 180 | 0 | 120 | 100 | 100 |
| anyio | 200 | 380 | 180 | 0 | 120 | 100 | 100 |
| langchain | 200 | 380 | 180 | 0 | 120 | 100 | 100 |

## R3 (240 tasks)

| baseline | complete | safe | duplicate | stale | stale source |
|---|---:|---:|---:|---:|---|
| langgraph | 120 | 40 | 40 | 60 | result.json (attempts not persisted) |
| temporal | 120 | 40 | 40 | 60 | attempts.sqlite |

## R4 (80 tasks)

| source | safe | complete | duplicate | stale | CLEAR safe |
|---|---:|---:|---:|---:|---:|
| smolagents | 16 | 29 | 11 | 2 | 6 |
| pydantic_ai | 16 | 29 | 11 | 2 | 6 |

## R5 (400 tasks)

| policy | safe | complete(rows=1) | duplicate | stale | aborted |
|---|---:|---:|---:|---:|---:|
| clear | 40 | 40 | 0 | 0 | 80 |
| idem_retry | 20 | 40 | 40 | 40 | 0 |
| query_retry | 20 | 40 | 40 | 40 | 0 |
| reauth_retry | 40 | 40 | 40 | 0 | 0 |
| pause | 0 | 0 | 0 | 0 | 0 |

## R7 (1,200 tasks, ms)

| policy | safe | complete | duplicate | stale | control p50 | control p95 | active p50 | wait p50 | actions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| clear | 250 | 250 | 0 | 0 | 7.58 | 29.121 | 6.596 | 0.205 | 1.83 |
| idem_retry | 50 | 300 | 200 | 50 | 7.218 | 9.76 | 7.118 | 0.0 | 1.0 |
| query_retry | 200 | 300 | 50 | 50 | 4.367 | 11.605 | 4.291 | 0.0 | 1.5 |
| pause | 0 | 0 | 0 | 0 | 0.006 | 0.01 | 0.0 | 0.0 | 0.0 |

## R8 (450 tasks)

| variant | safe | complete | duplicate | pause | stale permit | stale manifest |
|---|---:|---:|---:|---:|---:|---:|
| full | 50 | 50 | 0 | 40 | 0 | 0 |
| no_closure | 30 | 50 | 20 | 40 | 0 | 0 |
| no_query | 30 | 60 | 30 | 30 | 0 | 0 |
| no_version | 50 | 60 | 0 | 30 | 0 | 10 |
| no_atomic | 50 | 60 | 0 | 30 | 10 | 0 |

## R9 (static audit)

| source | adapter LOC | methods | shims |
|---|---:|---:|---:|
| mcp | 149 | 11 | 5 |
| anyio | 138 | 11 | 5 |
| langchain | 57 | 3 | 5 |
| smolagents | 22 | 2 | 5 |
| pydantic_ai | 16 | 2 | 5 |

## R4 10-seed extension (800 tasks)

| source | policy | tasks | safe | complete | duplicate | stale | pause |
|---|---|---:|---:|---:|---:|---:|---:|
| smolagents | clear | 80 | 60 | 60 | 0 | 0 | 20 |
| smolagents | idem_retry | 80 | 20 | 80 | 50 | 10 | 0 |
| smolagents | query_retry | 80 | 50 | 70 | 10 | 10 | 10 |
| smolagents | reauth_retry | 80 | 30 | 80 | 50 | 0 | 0 |
| smolagents | pause | 80 | 0 | 0 | 0 | 0 | 80 |
| pydantic_ai | clear | 80 | 60 | 60 | 0 | 0 | 20 |
| pydantic_ai | idem_retry | 80 | 20 | 80 | 50 | 10 | 0 |
| pydantic_ai | query_retry | 80 | 50 | 70 | 10 | 10 | 10 |
| pydantic_ai | reauth_retry | 80 | 30 | 80 | 50 | 0 | 0 |
| pydantic_ai | pause | 80 | 0 | 0 | 0 | 0 | 80 |

## R14 extended hold-out sources (800 tasks)

| source | policy | tasks | safe | complete | duplicate | stale | pause |
|---|---|---:|---:|---:|---:|---:|---:|
| llamaindex | clear | 80 | 60 | 60 | 0 | 0 | 20 |
| llamaindex | idem_retry | 80 | 20 | 80 | 50 | 10 | 0 |
| llamaindex | query_retry | 80 | 50 | 70 | 10 | 10 | 10 |
| llamaindex | reauth_retry | 80 | 30 | 80 | 50 | 0 | 0 |
| llamaindex | pause | 80 | 0 | 0 | 0 | 0 | 80 |
| autogen | clear | 80 | 60 | 60 | 0 | 0 | 20 |
| autogen | idem_retry | 80 | 20 | 80 | 50 | 10 | 0 |
| autogen | query_retry | 80 | 50 | 70 | 10 | 10 | 10 |
| autogen | reauth_retry | 80 | 30 | 80 | 50 | 0 | 0 |
| autogen | pause | 80 | 0 | 0 | 0 | 0 | 80 |

## R11 real process crash (250 tasks)

| policy | tasks | safe | complete | duplicate | stale | pause |
|---|---:|---:|---:|---:|---:|---:|
| clear | 50 | 20 | 20 | 0 | 0 | 30 |
| idem_retry | 50 | 10 | 50 | 30 | 20 | 0 |
| query_retry | 50 | 30 | 40 | 0 | 10 | 10 |
| reauth_retry | 50 | 20 | 50 | 30 | 0 | 0 |
| pause | 50 | 0 | 0 | 0 | 0 | 50 |

R11 CLEAR cells:

| condition | terminal | rows |
|---|---|---:|
| crash_after_commit | complete | 1 |
| crash_before_commit | pause | 0 |
| crash_after_commit_revoke | complete | 1 |
| crash_before_commit_revoke | pause | 0 |
| crash_after_commit_no_query | pause | 1 |

## R13 change-after-evidence (800 tasks)

| source | tasks | safe | complete | duplicate | stale | pause | unqualified | atomic rejected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| anyio | 400 | 120 | 240 | 0 | 60 | 160 | 60 | 20 |
| langchain | 400 | 120 | 240 | 0 | 60 | 160 | 60 | 20 |

## R15 end-to-end five-step workflow (800 workflows)

| config | policy | workflows | safe | complete | duplicates | stale rows | pauses | orphan | step POSTs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| idem_on | clear | 80 | 40 | 40 | 0 | 0 | 40 | 40 | 320 |
| idem_on | idem_retry | 80 | 40 | 80 | 0 | 80 | 0 | 0 | 440 |
| idem_on | query_retry | 80 | 40 | 80 | 0 | 80 | 0 | 0 | 400 |
| idem_on | reauth_retry | 80 | 40 | 80 | 0 | 80 | 0 | 0 | 440 |
| idem_on | pause | 80 | 0 | 40 | 0 | 80 | 40 | 40 | 340 |
| idem_off | clear | 80 | 40 | 40 | 0 | 0 | 40 | 40 | 320 |
| idem_off | idem_retry | 80 | 0 | 80 | 40 | 80 | 0 | 0 | 440 |
| idem_off | query_retry | 80 | 40 | 80 | 0 | 80 | 0 | 0 | 400 |
| idem_off | reauth_retry | 80 | 0 | 80 | 40 | 80 | 0 | 0 | 440 |
| idem_off | pause | 80 | 0 | 40 | 0 | 80 | 40 | 40 | 340 |

## R16 fair baselines (320 workflows)

| baseline | config | workflows | safe | complete | duplicates | stale rows |
|---|---|---:|---:|---:|---:|---:|
| temporal | idem_on | 80 | 40 | 80 | 0 | 80 |
| temporal | idem_off | 80 | 0 | 80 | 40 | 80 |
| langgraph | idem_on | 80 | 40 | 80 | 0 | 80 |
| langgraph | idem_off | 80 | 0 | 80 | 40 | 80 |

## R17 Z3 inductive model

| item | result |
|---|---|
| T1_retry_soundness | unsat |
| T2_admission_atomicity | unsat |
| T4_requalification | unsat |
| all_assumptions_safe | unsat |
| T3_incomplete_evidence_impossibility | unsat |
| no_A1_faithful_query | sat |
| no_A2_lifecycle_closure | sat |
| no_A3_version_binding | sat |
| no_A4_atomic_admission | sat |

## R18 evidence-surface degradation (1200 workflows)

| config | policy | workflows | safe | complete | duplicates | pauses |
|---|---|---:|---:|---:|---:|---:|
| on_faithful | clear | 40 | 40 | 40 | 0 | 0 |
| on_faithful | idem_retry | 40 | 40 | 40 | 0 | 0 |
| on_faithful | query_retry | 40 | 40 | 40 | 0 | 0 |
| on_faithful | reauth_retry | 40 | 40 | 40 | 0 | 0 |
| on_faithful | pause | 40 | 0 | 0 | 0 | 40 |
| on_stale | clear | 40 | 40 | 40 | 0 | 0 |
| on_stale | idem_retry | 40 | 40 | 40 | 0 | 0 |
| on_stale | query_retry | 40 | 40 | 40 | 0 | 0 |
| on_stale | reauth_retry | 40 | 40 | 40 | 0 | 0 |
| on_stale | pause | 40 | 0 | 0 | 0 | 40 |
| on_unavailable | clear | 40 | 40 | 40 | 0 | 0 |
| on_unavailable | idem_retry | 40 | 40 | 40 | 0 | 0 |
| on_unavailable | query_retry | 40 | 0 | 0 | 0 | 40 |
| on_unavailable | reauth_retry | 40 | 40 | 40 | 0 | 0 |
| on_unavailable | pause | 40 | 0 | 0 | 0 | 40 |
| off_faithful | clear | 40 | 40 | 40 | 0 | 0 |
| off_faithful | idem_retry | 40 | 0 | 40 | 40 | 0 |
| off_faithful | query_retry | 40 | 40 | 40 | 0 | 0 |
| off_faithful | reauth_retry | 40 | 0 | 40 | 40 | 0 |
| off_faithful | pause | 40 | 0 | 0 | 0 | 40 |
| off_stale | clear | 40 | 40 | 40 | 0 | 0 |
| off_stale | idem_retry | 40 | 0 | 40 | 40 | 0 |
| off_stale | query_retry | 40 | 0 | 40 | 40 | 0 |
| off_stale | reauth_retry | 40 | 0 | 40 | 40 | 0 |
| off_stale | pause | 40 | 0 | 0 | 0 | 40 |
| off_unavailable | clear | 40 | 40 | 40 | 0 | 0 |
| off_unavailable | idem_retry | 40 | 0 | 40 | 40 | 0 |
| off_unavailable | query_retry | 40 | 0 | 0 | 0 | 40 |
| off_unavailable | reauth_retry | 40 | 0 | 40 | 40 | 0 |
| off_unavailable | pause | 40 | 0 | 0 | 0 | 40 |

## R19 evidence redundancy and forged receipts

| config | policy | workflows | safe | complete | duplicates | false complete | pauses |
|---|---|---:|---:|---:|---:|---:|---:|
| on-faithful-faithful | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-faithful | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-faithful | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-faithful | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-faithful | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-faithful-stale | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-stale | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-stale | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-stale | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-stale | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-faithful-unavailable | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-unavailable | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-unavailable | query_retry | 20 | 0 | 0 | 0 | 0 | 20 |
| on-faithful-unavailable | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-unavailable | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-faithful | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-faithful | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-faithful | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-faithful | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-faithful | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-stale | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-stale | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-stale | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-stale | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-stale | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-unavailable | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-unavailable | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-unavailable | query_retry | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-unavailable | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-unavailable | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-faithful-faithful | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| off-faithful-faithful | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-faithful | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| off-faithful-faithful | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-faithful | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-faithful-stale | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| off-faithful-stale | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-stale | query_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-stale | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-stale | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-faithful-unavailable | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| off-faithful-unavailable | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-unavailable | query_retry | 20 | 0 | 0 | 0 | 0 | 20 |
| off-faithful-unavailable | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-faithful-unavailable | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-faithful | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| off-lost-faithful | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-faithful | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| off-lost-faithful | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-faithful | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-stale | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-stale | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-stale | query_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-stale | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-stale | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-unavailable | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-unavailable | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-unavailable | query_retry | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-unavailable | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| off-lost-unavailable | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-faithful-forged | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| on-faithful-forged | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-forged | query_retry | 20 | 0 | 0 | 0 | 20 | 0 |
| on-faithful-forged | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-faithful-forged | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-forged | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| on-lost-forged | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-forged | query_retry | 20 | 0 | 0 | 0 | 20 | 0 |
| on-lost-forged | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| on-lost-forged | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-faithful-forged | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| off-faithful-forged | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| off-faithful-forged | query_retry | 20 | 0 | 0 | 0 | 20 | 0 |
| off-faithful-forged | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| off-faithful-forged | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-forged | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| off-lost-forged | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| off-lost-forged | query_retry | 20 | 0 | 0 | 0 | 20 | 0 |
| off-lost-forged | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| off-lost-forged | pause | 20 | 0 | 0 | 0 | 0 | 20 |

## R20 multi-fault and randomised placement

| config | policy | workflows | safe | complete | duplicates | false complete | pauses |
|---|---|---:|---:|---:|---:|---:|---:|
| single_lost-on | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| single_lost-on | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_lost-on | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_lost-on | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_lost-on | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| single_lost-off | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| single_lost-off | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| single_lost-off | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_lost-off | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| single_lost-off | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| single_late-on | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| single_late-on | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_late-on | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_late-on | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_late-on | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| single_late-off | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| single_late-off | idem_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| single_late-off | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| single_late-off | reauth_retry | 20 | 0 | 20 | 20 | 0 | 0 |
| single_late-off | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| double_lost-on | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| double_lost-on | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| double_lost-on | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| double_lost-on | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| double_lost-on | pause | 20 | 0 | 0 | 0 | 0 | 20 |
| double_lost-off | clear | 20 | 20 | 20 | 0 | 0 | 0 |
| double_lost-off | idem_retry | 20 | 0 | 20 | 40 | 0 | 0 |
| double_lost-off | query_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| double_lost-off | reauth_retry | 20 | 0 | 20 | 40 | 0 | 0 |
| double_lost-off | pause | 20 | 0 | 0 | 0 | 0 | 20 |

## R21 concurrency (800 workflows)

| config | policy | workflows | safe | complete | duplicates | pauses |
|---|---|---:|---:|---:|---:|---:|
| c8-on | clear | 40 | 40 | 40 | 0 | 0 |
| c8-on | idem_retry | 40 | 40 | 40 | 0 | 0 |
| c8-on | query_retry | 40 | 40 | 40 | 0 | 0 |
| c8-on | reauth_retry | 40 | 40 | 40 | 0 | 0 |
| c8-on | pause | 40 | 0 | 0 | 0 | 40 |
| c8-off | clear | 40 | 40 | 40 | 0 | 0 |
| c8-off | idem_retry | 40 | 0 | 40 | 40 | 0 |
| c8-off | query_retry | 40 | 40 | 40 | 0 | 0 |
| c8-off | reauth_retry | 40 | 0 | 40 | 40 | 0 |
| c8-off | pause | 40 | 0 | 0 | 0 | 40 |
| c32-on | clear | 40 | 40 | 40 | 0 | 0 |
| c32-on | idem_retry | 40 | 40 | 40 | 0 | 0 |
| c32-on | query_retry | 40 | 40 | 40 | 0 | 0 |
| c32-on | reauth_retry | 40 | 40 | 40 | 0 | 0 |
| c32-on | pause | 40 | 0 | 0 | 0 | 40 |
| c32-off | clear | 40 | 40 | 40 | 0 | 0 |
| c32-off | idem_retry | 40 | 0 | 40 | 40 | 0 |
| c32-off | query_retry | 40 | 40 | 40 | 0 | 0 |
| c32-off | reauth_retry | 40 | 0 | 40 | 40 | 0 |
| c32-off | pause | 40 | 0 | 0 | 0 | 40 |

| config | concurrency | wall s | workflows/s | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| c8-on | 8 | 22.541 | 8.873 | 1546.85 | 1636.51 |
| c8-off | 8 | 22.852 | 8.752 | 1545.63 | 1668.39 |
| c32-on | 32 | 8.72 | 22.935 | 1559.64 | 1900.88 |
| c32-off | 32 | 8.523 | 23.466 | 1543.49 | 1975.81 |

## R22 steady-state cost (200 workflows, no faults)

| policy | workflows | safe | complete | duplicates | pauses |
|---|---:|---:|---:|---:|---:|
| clear | 40 | 40 | 40 | 0 | 0 |
| idem_retry | 40 | 40 | 40 | 0 | 0 |
| query_retry | 40 | 40 | 40 | 0 | 0 |
| reauth_retry | 40 | 40 | 40 | 0 | 0 |
| pause | 40 | 40 | 40 | 0 | 0 |

## R23 idempotency key stability (160 workflows)

| config | policy | workflows | safe | complete | duplicates | pauses |
|---|---|---:|---:|---:|---:|---:|
| idem_on | clear | 40 | 40 | 40 | 0 | 0 |
| idem_on | idem_retry | 40 | 40 | 40 | 0 | 0 |
| idem_on | idem_fresh | 40 | 0 | 40 | 40 | 0 |
| idem_on | pause | 40 | 0 | 0 | 0 | 40 |

## R24 resumable pause (160 workflows, idempotency off)

| condition | policy | workflows | safe | complete | duplicates | pauses |
|---|---|---:|---:|---:|---:|---:|
| revoke_at_attach | clear | 20 | 0 | 0 | 0 | 20 |
| revoke_at_attach | clear_replay | 20 | 20 | 20 | 0 | 0 |
| revoke_at_attach | clear_resume | 20 | 20 | 20 | 0 | 0 |
| revoke_at_attach | idem_retry | 20 | 0 | 20 | 0 | 0 |
| blackout_at_attach | clear | 20 | 0 | 0 | 0 | 20 |
| blackout_at_attach | clear_replay | 20 | 0 | 20 | 20 | 0 |
| blackout_at_attach | clear_resume | 20 | 20 | 20 | 0 | 0 |
| blackout_at_attach | idem_retry | 20 | 0 | 20 | 20 | 0 |

## R29 evidence storage cost

| config | workflows | bytes/workflow | receipts | effect rows |
|---|---:|---:|---:|---:|
| n25 | 25 | 24576.0 | 125 | 125 |
| n50 | 50 | 24576.0 | 250 | 250 |
| n100 | 100 | 24576.0 | 500 | 500 |

## R30 evidence outage (400 workflows)

| config | policy | workflows | safe | complete | duplicates | pauses |
|---|---|---:|---:|---:|---:|---:|
| lifecycle_down-on | clear | 20 | 20 | 20 | 0 | 0 |
| lifecycle_down-on | idem_retry | 20 | 20 | 20 | 0 | 0 |
| lifecycle_down-on | query_retry | 20 | 20 | 20 | 0 | 0 |
| lifecycle_down-on | reauth_retry | 20 | 20 | 20 | 0 | 0 |
| lifecycle_down-on | pause | 20 | 0 | 0 | 0 | 20 |
| lifecycle_down-off | clear | 20 | 20 | 20 | 0 | 0 |
| lifecycle_down-off | idem_retry | 20 | 0 | 20 | 20 | 0 |
| lifecycle_down-off | query_retry | 20 | 20 | 20 | 0 | 0 |
| lifecycle_down-off | reauth_retry | 20 | 0 | 20 | 20 | 0 |
| lifecycle_down-off | pause | 20 | 0 | 0 | 0 | 20 |
| all_down-on | clear | 20 | 0 | 0 | 0 | 20 |
| all_down-on | idem_retry | 20 | 20 | 20 | 0 | 0 |
| all_down-on | query_retry | 20 | 0 | 0 | 0 | 20 |
| all_down-on | reauth_retry | 20 | 20 | 20 | 0 | 0 |
| all_down-on | pause | 20 | 0 | 0 | 0 | 20 |
| all_down-off | clear | 20 | 0 | 0 | 0 | 20 |
| all_down-off | idem_retry | 20 | 0 | 20 | 20 | 0 |
| all_down-off | query_retry | 20 | 0 | 0 | 0 | 20 |
| all_down-off | reauth_retry | 20 | 0 | 20 | 20 | 0 |
| all_down-off | pause | 20 | 0 | 0 | 0 | 20 |

## R33 WAN cost (150 workflows)

| config | policy | workflows | safe | complete | duplicates |
|---|---|---:|---:|---:|---:|
| rtt1 | clear | 10 | 10 | 10 | 0 |
| rtt1 | idem_retry | 10 | 10 | 10 | 0 |
| rtt1 | query_retry | 10 | 10 | 10 | 0 |
| rtt1 | reauth_retry | 10 | 10 | 10 | 0 |
| rtt1 | pause | 10 | 10 | 10 | 0 |
| rtt20 | clear | 10 | 10 | 10 | 0 |
| rtt20 | idem_retry | 10 | 10 | 10 | 0 |
| rtt20 | query_retry | 10 | 10 | 10 | 0 |
| rtt20 | reauth_retry | 10 | 10 | 10 | 0 |
| rtt20 | pause | 10 | 10 | 10 | 0 |
| rtt80 | clear | 10 | 10 | 10 | 0 |
| rtt80 | idem_retry | 10 | 10 | 10 | 0 |
| rtt80 | query_retry | 10 | 10 | 10 | 0 |
| rtt80 | reauth_retry | 10 | 10 | 10 | 0 |
| rtt80 | pause | 10 | 10 | 10 | 0 |

## R25 payment domain (400 workflows)

| config | policy | workflows | safe | complete | duplicates |
|---|---|---:|---:|---:|---:|
| idem_on | clear | 40 | 40 | 40 | 0 |
| idem_on | idem_retry | 40 | 40 | 40 | 0 |
| idem_on | query_retry | 40 | 40 | 40 | 0 |
| idem_on | reauth_retry | 40 | 40 | 40 | 0 |
| idem_on | pause | 40 | 0 | 0 | 0 |
| idem_off | clear | 40 | 40 | 40 | 0 |
| idem_off | idem_retry | 40 | 0 | 40 | 40 |
| idem_off | query_retry | 40 | 40 | 40 | 0 |
| idem_off | reauth_retry | 40 | 0 | 40 | 40 |
| idem_off | pause | 40 | 0 | 0 | 0 |

## R26 instrumentation ladder (240 workflows)

| level | policy | workflows | safe | complete | duplicates | pauses |
|---|---|---:|---:|---:|---:|---:|
| L0 | clear | 20 | 0 | 0 | 0 | 20 |
| L0 | idem_retry | 20 | 0 | 20 | 20 | 0 |
| L0 | query_retry | 20 | 0 | 0 | 0 | 20 |
| L1 | clear | 20 | 0 | 0 | 0 | 20 |
| L1 | idem_retry | 20 | 0 | 20 | 20 | 0 |
| L1 | query_retry | 20 | 0 | 0 | 0 | 20 |
| L2 | clear | 20 | 20 | 20 | 0 | 0 |
| L2 | idem_retry | 20 | 0 | 20 | 20 | 0 |
| L2 | query_retry | 20 | 0 | 0 | 0 | 20 |
| L3 | clear | 20 | 20 | 20 | 0 | 0 |
| L3 | idem_retry | 20 | 0 | 20 | 20 | 0 |
| L3 | query_retry | 20 | 20 | 20 | 0 | 0 |

## R31 cross-tenant receipt binding (101 workflows)

| config | policy | workflows | safe | complete | duplicates | false complete | pauses |
|---|---|---:|---:|---:|---:|---:|---:|
| tenant | donor | 1 | 1 | 1 | 0 | 0 | 0 |
| tenant | clear | 20 | 0 | 0 | 0 | 0 | 20 |
| tenant | idem_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| tenant | query_retry | 20 | 0 | 0 | 0 | 20 | 0 |
| tenant | reauth_retry | 20 | 20 | 20 | 0 | 0 | 0 |
| tenant | pause | 20 | 0 | 0 | 0 | 0 | 20 |

## R32 offline audit of frozen effect logs (1,001 workflows)

| run/config | workflows | duplicate rows | stale rows | unbound receipts | inconsistent ops | false-complete-like |
|---|---:|---:|---:|---:|---:|---:|
| R15/attempt2/idem_off | 400 | 80 | 320 | 0 | 0 | 0 |
| R18/attempt1/off_stale | 200 | 120 | 0 | 0 | 0 | 0 |
| R19/attempt2/off-faithful-forged | 100 | 0 | 0 | 0 | 60 | 20 |
| R21/attempt9/c32-off | 200 | 80 | 0 | 0 | 0 | 0 |
| R31/attempt1/tenant | 101 | 0 | 0 | 0 | 60 | 20 |

## R27 decorator path (3 sources x 8 conditions x 5 seeds)

| source | seed | condition | terminal | rows |
|---|---:|---|---|---:|
| smolagents | 1 | C01_fail_before | complete | 1 |
| smolagents | 1 | C02_lost_return | complete | 1 |
| smolagents | 1 | C03_late_commit | complete | 1 |
| smolagents | 1 | C04_revoke | pause | 0 |
| smolagents | 1 | C05_query_unavailable | pause | 1 |
| smolagents | 1 | C06_closure_missing | complete | 1 |
| smolagents | 1 | C07_idempotent_lost | complete | 1 |
| smolagents | 1 | C08_normal | complete | 1 |
| smolagents | 2 | C01_fail_before | complete | 1 |
| smolagents | 2 | C02_lost_return | complete | 1 |
| smolagents | 2 | C03_late_commit | complete | 1 |
| smolagents | 2 | C04_revoke | pause | 0 |
| smolagents | 2 | C05_query_unavailable | pause | 1 |
| smolagents | 2 | C06_closure_missing | complete | 1 |
| smolagents | 2 | C07_idempotent_lost | complete | 1 |
| smolagents | 2 | C08_normal | complete | 1 |
| smolagents | 3 | C01_fail_before | complete | 1 |
| smolagents | 3 | C02_lost_return | complete | 1 |
| smolagents | 3 | C03_late_commit | complete | 1 |
| smolagents | 3 | C04_revoke | pause | 0 |
| smolagents | 3 | C05_query_unavailable | pause | 1 |
| smolagents | 3 | C06_closure_missing | complete | 1 |
| smolagents | 3 | C07_idempotent_lost | complete | 1 |
| smolagents | 3 | C08_normal | complete | 1 |
| smolagents | 4 | C01_fail_before | complete | 1 |
| smolagents | 4 | C02_lost_return | complete | 1 |
| smolagents | 4 | C03_late_commit | complete | 1 |
| smolagents | 4 | C04_revoke | pause | 0 |
| smolagents | 4 | C05_query_unavailable | pause | 1 |
| smolagents | 4 | C06_closure_missing | complete | 1 |
| smolagents | 4 | C07_idempotent_lost | complete | 1 |
| smolagents | 4 | C08_normal | complete | 1 |
| smolagents | 5 | C01_fail_before | complete | 1 |
| smolagents | 5 | C02_lost_return | complete | 1 |
| smolagents | 5 | C03_late_commit | complete | 1 |
| smolagents | 5 | C04_revoke | pause | 0 |
| smolagents | 5 | C05_query_unavailable | pause | 1 |
| smolagents | 5 | C06_closure_missing | complete | 1 |
| smolagents | 5 | C07_idempotent_lost | complete | 1 |
| smolagents | 5 | C08_normal | complete | 1 |
| pydantic_ai | 1 | C01_fail_before | complete | 1 |
| pydantic_ai | 1 | C02_lost_return | complete | 1 |
| pydantic_ai | 1 | C03_late_commit | complete | 1 |
| pydantic_ai | 1 | C04_revoke | pause | 0 |
| pydantic_ai | 1 | C05_query_unavailable | pause | 1 |
| pydantic_ai | 1 | C06_closure_missing | complete | 1 |
| pydantic_ai | 1 | C07_idempotent_lost | complete | 1 |
| pydantic_ai | 1 | C08_normal | complete | 1 |
| pydantic_ai | 2 | C01_fail_before | complete | 1 |
| pydantic_ai | 2 | C02_lost_return | complete | 1 |
| pydantic_ai | 2 | C03_late_commit | complete | 1 |
| pydantic_ai | 2 | C04_revoke | pause | 0 |
| pydantic_ai | 2 | C05_query_unavailable | pause | 1 |
| pydantic_ai | 2 | C06_closure_missing | complete | 1 |
| pydantic_ai | 2 | C07_idempotent_lost | complete | 1 |
| pydantic_ai | 2 | C08_normal | complete | 1 |
| pydantic_ai | 3 | C01_fail_before | complete | 1 |
| pydantic_ai | 3 | C02_lost_return | complete | 1 |
| pydantic_ai | 3 | C03_late_commit | complete | 1 |
| pydantic_ai | 3 | C04_revoke | pause | 0 |
| pydantic_ai | 3 | C05_query_unavailable | pause | 1 |
| pydantic_ai | 3 | C06_closure_missing | complete | 1 |
| pydantic_ai | 3 | C07_idempotent_lost | complete | 1 |
| pydantic_ai | 3 | C08_normal | complete | 1 |
| pydantic_ai | 4 | C01_fail_before | complete | 1 |
| pydantic_ai | 4 | C02_lost_return | complete | 1 |
| pydantic_ai | 4 | C03_late_commit | complete | 1 |
| pydantic_ai | 4 | C04_revoke | pause | 0 |
| pydantic_ai | 4 | C05_query_unavailable | pause | 1 |
| pydantic_ai | 4 | C06_closure_missing | complete | 1 |
| pydantic_ai | 4 | C07_idempotent_lost | complete | 1 |
| pydantic_ai | 4 | C08_normal | complete | 1 |
| pydantic_ai | 5 | C01_fail_before | complete | 1 |
| pydantic_ai | 5 | C02_lost_return | complete | 1 |
| pydantic_ai | 5 | C03_late_commit | complete | 1 |
| pydantic_ai | 5 | C04_revoke | pause | 0 |
| pydantic_ai | 5 | C05_query_unavailable | pause | 1 |
| pydantic_ai | 5 | C06_closure_missing | complete | 1 |
| pydantic_ai | 5 | C07_idempotent_lost | complete | 1 |
| pydantic_ai | 5 | C08_normal | complete | 1 |
| llamaindex | 1 | C01_fail_before | complete | 1 |
| llamaindex | 1 | C02_lost_return | complete | 1 |
| llamaindex | 1 | C03_late_commit | complete | 1 |
| llamaindex | 1 | C04_revoke | pause | 0 |
| llamaindex | 1 | C05_query_unavailable | pause | 1 |
| llamaindex | 1 | C06_closure_missing | complete | 1 |
| llamaindex | 1 | C07_idempotent_lost | complete | 1 |
| llamaindex | 1 | C08_normal | complete | 1 |
| llamaindex | 2 | C01_fail_before | complete | 1 |
| llamaindex | 2 | C02_lost_return | complete | 1 |
| llamaindex | 2 | C03_late_commit | complete | 1 |
| llamaindex | 2 | C04_revoke | pause | 0 |
| llamaindex | 2 | C05_query_unavailable | pause | 1 |
| llamaindex | 2 | C06_closure_missing | complete | 1 |
| llamaindex | 2 | C07_idempotent_lost | complete | 1 |
| llamaindex | 2 | C08_normal | complete | 1 |
| llamaindex | 3 | C01_fail_before | complete | 1 |
| llamaindex | 3 | C02_lost_return | complete | 1 |
| llamaindex | 3 | C03_late_commit | complete | 1 |
| llamaindex | 3 | C04_revoke | pause | 0 |
| llamaindex | 3 | C05_query_unavailable | pause | 1 |
| llamaindex | 3 | C06_closure_missing | complete | 1 |
| llamaindex | 3 | C07_idempotent_lost | complete | 1 |
| llamaindex | 3 | C08_normal | complete | 1 |
| llamaindex | 4 | C01_fail_before | complete | 1 |
| llamaindex | 4 | C02_lost_return | complete | 1 |
| llamaindex | 4 | C03_late_commit | complete | 1 |
| llamaindex | 4 | C04_revoke | pause | 0 |
| llamaindex | 4 | C05_query_unavailable | pause | 1 |
| llamaindex | 4 | C06_closure_missing | complete | 1 |
| llamaindex | 4 | C07_idempotent_lost | complete | 1 |
| llamaindex | 4 | C08_normal | complete | 1 |
| llamaindex | 5 | C01_fail_before | complete | 1 |
| llamaindex | 5 | C02_lost_return | complete | 1 |
| llamaindex | 5 | C03_late_commit | complete | 1 |
| llamaindex | 5 | C04_revoke | pause | 0 |
| llamaindex | 5 | C05_query_unavailable | pause | 1 |
| llamaindex | 5 | C06_closure_missing | complete | 1 |
| llamaindex | 5 | C07_idempotent_lost | complete | 1 |
| llamaindex | 5 | C08_normal | complete | 1 |

Guard core: 25 lines.

## R28 third-party MCP servers (320 workflows)

| server/fault/policy | complete | duplicates | safe |
|---|---:|---:|---:|

## R34 concurrent dual controllers (120 workflows)

| fault/mechanism | attach rows | duplicates | safe |
|---|---:|---:|---:|
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/none | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/lease | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_return/unique | 1 | 0 | True |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/none | 2 | 1 | False |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/lease | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |
| lost_before_commit/unique | 1 | 0 | True |

## R35 same-evidence baseline (120 workflows)

| condition/policy | attach rows | stale | completed |
|---|---:|---:|---:|
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/clear | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_return/verify_retry | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/clear | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| lost_before_commit/verify_retry | 1 | 0 | True |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/clear | 0 | 0 | False |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |
| revoke_race/verify_retry | 1 | 1 | True |

## R38 fence-ordered settlement (280 workflows)

| closure/fault/policy | attach rows | completed | rejected |
|---|---:|---|---:|
| faithful/late_effect/clear | 1 | True | 0 |
| faithful/late_effect/blind_retry | 2 | True | 0 |
| faithful/late_effect/pause | 1 | False | 0 |
| faithful/lost_before_commit/clear | 1 | True | 0 |
| faithful/lost_before_commit/blind_retry | 1 | True | 0 |
| faithful/lost_before_commit/pause | 0 | False | 0 |
| absent/late_effect/clear | 1 | False | 0 |
| absent/late_effect/clear_fenced | 1 | True | 1 |
| absent/late_effect/blind_retry | 2 | True | 0 |
| absent/late_effect/pause | 1 | False | 0 |
| absent/lost_before_commit/clear | 0 | False | 0 |
| absent/lost_before_commit/clear_fenced | 1 | True | 0 |
| absent/lost_before_commit/blind_retry | 1 | True | 0 |
| absent/lost_before_commit/pause | 0 | False | 0 |

## R36 frontier gate vs fence settlement (320 workflows)

| profile/fault/policy | attach rows | completed | rejected |
|---|---:|---|---:|
| buffered/late_effect/clear | 1 | False | 0 |
| buffered/late_effect/clear_fenced | 1 | True | 1 |
| buffered/late_effect/frontier | 1 | True | 1 |
| buffered/late_effect/blind_retry | 2 | True | 0 |
| buffered/lost_before_commit/clear | 0 | False | 0 |
| buffered/lost_before_commit/clear_fenced | 1 | True | 0 |
| buffered/lost_before_commit/frontier | 1 | True | 0 |
| buffered/lost_before_commit/blind_retry | 1 | True | 0 |
| immediate/late_effect/clear | 1 | False | 0 |
| immediate/late_effect/clear_fenced | 1 | True | 1 |
| immediate/late_effect/frontier | 1 | False | 0 |
| immediate/late_effect/blind_retry | 2 | True | 0 |
| immediate/lost_before_commit/clear | 0 | False | 0 |
| immediate/lost_before_commit/clear_fenced | 1 | True | 0 |
| immediate/lost_before_commit/frontier | 0 | False | 0 |
| immediate/lost_before_commit/blind_retry | 1 | True | 0 |

## R39 real LLM agent (84 runs)

| guard/fault | duplicates | rejected | completed |
|---|---:|---:|---:|
| blind/late_effect | 6 | 0 | 6 |
| blind/late_effect_slow | 6 | 0 | 6 |
| blind/lost_before_commit | 0 | 0 | 4 |
| blind/lost_return | 5 | 0 | 5 |
| blind/none | 0 | 0 | 4 |
| clear/late_effect | 0 | 6 | 6 |
| clear/late_effect_slow | 0 | 6 | 6 |
| clear/lost_before_commit | 0 | 0 | 6 |
| clear/lost_return | 0 | 0 | 6 |
| clear/none | 0 | 0 | 4 |
| evidence/late_effect | 0 | 0 | 6 |
| evidence/late_effect_slow | 1 | 0 | 1 |
| evidence/lost_before_commit | 0 | 0 | 3 |
| evidence/lost_return | 0 | 0 | 6 |
| evidence/none | 0 | 0 | 4 |

## R40 intent change and pause/repair (36 runs)

| scenario/guard | duplicates | mixed | stale | residual | followed | paused | recovered |
|---|---:|---:|---:|---:|---:|---:|---:|
| intent_change/blind | 12 | 12 | 0 | 6 | 6 | 0 | 0 |
| intent_change/clear | 0 | 0 | 0 | 6 | 6 | 0 | 0 |
| intent_change/evidence | 11 | 11 | 0 | 6 | 6 | 0 | 0 |
| no_fence_repair/blind | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| no_fence_repair/clear | 0 | 0 | 0 | 0 | 0 | 6 | 6 |
| no_fence_repair/evidence | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## R41 concurrent model check (2 controllers)

| config | duplicate reachable |
|---|---|
| t5_atomic_admit | False |
| t5_lease | False |
| t5_no_a6 | True |
| t6_both | False |
| t6_fence_only | True |
| t6_finalize_only | True |
| t6_neither | True |

## R42 T5/T6 unbounded inductive check

| config | safe |
|---|---|
| t5_atomic_admit | True |
| t5_lease_closed | True |
| t5_lease_naive | False |
| t5_no_a6 | False |
| t6_both | True |
| t6_fence_only | False |
| t6_finalize_only | False |
| t6_neither | False |

## R43 Atomix original system (b3 irreversible)

| baseline | leaks (invalid sends) |
|---|---:|
| Atomix-MisclassifiedIrreversible | 300 |
| Checkpoint-Replay | 200 |
| Mutex+WAL+Rollback | 0 |
| No-Tx | 500 |
| Saga-Compensation | 400 |
| TCC-Confirm | 0 |
| Tx-Full | 0 |

## R44 equal-capability comparison (198 tasks)

| scenario | policy | safe | duplicates | false complete |
|---|---|---:|---:|---:|
| A | fenced | 60 | 0 | - |
| A | dedup_versioned | 60 | 0 | - |
| A | dedup_fresh | 20 | 40 | - |
| B | fenced | - | - | 0 |
| B | dedup_versioned | - | - | 0 |
| B | dedup_unversioned | - | - | 6 |

