| source | adapter class | adapter LOC | methods | per-condition branches | native effects/lifecycle | issues |
|---|---|---:|---:|---:|---|---:|
| mcp | `Host` | 149 | 11 | 0 | no / no | 4 |
| anyio | `Host` | 138 | 11 | 0 | no / no | 2 |
| langchain | `Host` | 57 | 3 | 0 | no / no | 2 |
| smolagents | `SmolagentsAdapter` | 22 | 2 | 0 | no / no | 2 |
| pydantic_ai | `PydanticAIAdapter` | 16 | 2 | 0 | no / no | 3 |

Host shims: `describe`, `effects`, `status`, `reauthorize`, `drain`
Host shim coverage: mcp 5/5, anyio 5/5, langchain 5/5, smolagents 5/5, pydantic_ai 5/5

Config fields: 12; shared control LOC: 209; total adapter LOC: 382

Issues: 16 total, 0 unresolved; categories: {'FIXTURE': 5, 'VERIFY': 3, 'API': 3, 'PKG': 2, 'CANCEL': 1, 'EV': 2}

Acceptance: {"zero_condition_branches": true, "shims_documented": true, "no_unresolved": true, "frozen_unchanged": true}
