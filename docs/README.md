# Experiment documents

English protocol and result records for every experiment cited by the paper.
Detailed per-task data live under the frozen run directories; each checker
recomputes the reported numbers from those records.

| ID | Record | Frozen run | Checks |
|---|---|---|---:|
| R1 | [R1_capability_space_preregistration.md](R1_capability_space_preregistration.md) | `runs/R1/attempt2 and runs/R1/seed1..9; runs/R1_anyio/attempt1 and seeds; runs/R1_langchain/attempt2 and seeds` | 1,909 checks per source round; 57,230 checks over the 10-seed extension |
| R2 | [R2_random_fault_campaign_protocol.md](R2_random_fault_campaign_protocol.md) | `runs/R2_mcp/attempt1, runs/R2_anyio/attempt1, runs/R2_langchain/attempt2` | 2,512 / 2,511 / 2,513 checks on the three sources |
| R3_LangGraph | [R3_LangGraph_baseline_protocol.md](R3_LangGraph_baseline_protocol.md) | `runs/R3_langgraph/attempt2` | 848 checks |
| R3_Temporal | [R3_Temporal_baseline_protocol.md](R3_Temporal_baseline_protocol.md) | `runs/R3_temporal/attempt3` | 910 checks |
| R4 | [R4_held_out_sources_protocol.md](R4_held_out_sources_protocol.md) | `runs/R4_smolagents/attempt1 and seed1..9; runs/R4_pydantic_ai/attempt1 and seed1..9; runs/R4_seeds/attempt1` | 140 checks per single-seed round; 149 checks in the 10-seed summary |
| R4 | [R4_held_out_sources_10seed_result.md](R4_held_out_sources_10seed_result.md) | `runs/R4_smolagents/attempt1 and seed1..9; runs/R4_pydantic_ai/attempt1 and seed1..9; runs/R4_seeds/attempt1` | 140 checks per single-seed round; 149 checks in the 10-seed summary |
| R14 | [R14_extended_held_out_sources_protocol.md](R14_extended_held_out_sources_protocol.md) | `runs/R4_llamaindex/attempt2 and seed1..9; runs/R4_autogen/attempt2 and seed1..9; runs/R14_seeds/attempt2` | 141 checks per single-seed round; 149 checks in the 10-seed summary |
| R14 | [R14_extended_held_out_sources_result.md](R14_extended_held_out_sources_result.md) | `runs/R4_llamaindex/attempt2 and seed1..9; runs/R4_autogen/attempt2 and seed1..9; runs/R14_seeds/attempt2` | 141 checks per single-seed round; 149 checks in the 10-seed summary |
| R5 | [R5_concurrent_retry_revocation_protocol.md](R5_concurrent_retry_revocation_protocol.md) | `runs/R5/attempt1` | 2,005 checks |
| R7 | [R7_overhead_protocol.md](R7_overhead_protocol.md) | `runs/R7/attempt2` | 3,609 checks |
| R8 | [R8_component_ablation_protocol.md](R8_component_ablation_protocol.md) | `runs/R8/attempt3` | 35 checks |
| R10 | [R10_artifact_reproduction_protocol.md](R10_artifact_reproduction_protocol.md) | `runs/R10/attempt49` | 6,749 checks |
| R11 | [R11_process_crash_protocol.md](R11_process_crash_protocol.md) | `runs/R11/attempt3` | 522 checks |
| R11 | [R11_process_crash_result.md](R11_process_crash_result.md) | `runs/R11/attempt3` | 522 checks |
| R13 | [R13_post_change_recovery_protocol.md](R13_post_change_recovery_protocol.md) | `runs/R13_anyio/attempt1, runs/R13_langchain/attempt1` | 1,859 (AnyIO) and 1,861 (LangChain) checks |
| R13 | [R13_post_change_recovery_result.md](R13_post_change_recovery_result.md) | `runs/R13_anyio/attempt1, runs/R13_langchain/attempt1` | 1,859 (AnyIO) and 1,861 (LangChain) checks |
| R15 | [R15_end_to_end_workflow_protocol.md](R15_end_to_end_workflow_protocol.md) | `runs/R15/attempt2` | 5,669 checks |
| R15 | [R15_end_to_end_workflow_result.md](R15_end_to_end_workflow_result.md) | `runs/R15/attempt2` | 5,669 checks |
| R16 | [R16_fair_baselines_protocol.md](R16_fair_baselines_protocol.md) | `runs/R16/attempt2` | 1,027 checks |
| R16 | [R16_fair_baselines_result.md](R16_fair_baselines_result.md) | `runs/R16/attempt2` | 1,027 checks |
| R18 | [R18_evidence_plane_degradation_protocol.md](R18_evidence_plane_degradation_protocol.md) | `runs/R18/attempt1` | 3,723 checks |
| R18 | [R18_evidence_plane_degradation_result.md](R18_evidence_plane_degradation_result.md) | `runs/R18/attempt1` | 3,723 checks |
| R19 | [R19_evidence_redundancy_binding_protocol.md](R19_evidence_redundancy_binding_protocol.md) | `runs/R19/attempt2` | 5,089 checks |
| R19 | [R19_evidence_redundancy_binding_result.md](R19_evidence_redundancy_binding_result.md) | `runs/R19/attempt2` | 5,089 checks |
| R20 | [R20_multi_fault_random_position_protocol.md](R20_multi_fault_random_position_protocol.md) | `runs/R20/attempt1` | 2,821 checks |
| R20 | [R20_multi_fault_random_position_result.md](R20_multi_fault_random_position_result.md) | `runs/R20/attempt1` | 2,821 checks |
| R21 | [R21_concurrency_throughput_protocol.md](R21_concurrency_throughput_protocol.md) | `runs/R21/attempt9` | 2,489 checks |
| R21 | [R21_concurrency_throughput_result.md](R21_concurrency_throughput_result.md) | `runs/R21/attempt9` | 2,489 checks |
| R22 | [R22_no_fault_cost_protocol.md](R22_no_fault_cost_protocol.md) | `runs/R22/attempt2` | 252 checks |
| R22 | [R22_no_fault_cost_result.md](R22_no_fault_cost_result.md) | `runs/R22/attempt2` | 252 checks |
| R23 | [R23_idempotency_key_stability_protocol.md](R23_idempotency_key_stability_protocol.md) | `runs/R23/attempt1` | 512 checks |
| R23 | [R23_idempotency_key_stability_result.md](R23_idempotency_key_stability_result.md) | `runs/R23/attempt1` | 512 checks |
| R24 | [R24_recoverable_pause_protocol.md](R24_recoverable_pause_protocol.md) | `runs/R24/attempt1` | 512 checks |
| R24 | [R24_recoverable_pause_result.md](R24_recoverable_pause_result.md) | `runs/R24/attempt1` | 512 checks |
| R25 | [R25_payment_domain_protocol.md](R25_payment_domain_protocol.md) | `runs/R25/attempt1` | 1,571 checks |
| R25 | [R25_payment_domain_result.md](R25_payment_domain_result.md) | `runs/R25/attempt1` | 1,571 checks |
| R26 | [R26_minimal_retrofit_ladder_protocol.md](R26_minimal_retrofit_ladder_protocol.md) | `runs/R26/attempt1` | 797 checks |
| R26 | [R26_minimal_retrofit_ladder_result.md](R26_minimal_retrofit_ladder_result.md) | `runs/R26/attempt1` | 797 checks |
| R27 | [R27_middleware_integration_protocol.md](R27_middleware_integration_protocol.md) | `runs/R27/attempt2` | 617 checks |
| R27 | [R27_middleware_integration_result.md](R27_middleware_integration_result.md) | `runs/R27/attempt2` | 617 checks |
| R28 | [R28_third_party_services_protocol.md](R28_third_party_services_protocol.md) | `runs/R28/attempt4` | 1,922 checks |
| R28 | [R28_third_party_services_result.md](R28_third_party_services_result.md) | `runs/R28/attempt4` | 1,922 checks |
| R29 | [R29_evidence_storage_cost_protocol.md](R29_evidence_storage_cost_protocol.md) | `runs/R29/attempt1` | 566 checks |
| R29 | [R29_evidence_storage_cost_result.md](R29_evidence_storage_cost_result.md) | `runs/R29/attempt1` | 566 checks |
| R30 | [R30_evidence_plane_outage_protocol.md](R30_evidence_plane_outage_protocol.md) | `runs/R30/attempt1` | 1,289 checks |
| R30 | [R30_evidence_plane_outage_result.md](R30_evidence_plane_outage_result.md) | `runs/R30/attempt1` | 1,289 checks |
| R31 | [R31_cross_tenant_binding_protocol.md](R31_cross_tenant_binding_protocol.md) | `runs/R31/attempt1` | 328 checks |
| R31 | [R31_cross_tenant_binding_result.md](R31_cross_tenant_binding_result.md) | `runs/R31/attempt1` | 328 checks |
| R32 | [R32_post_hoc_audit_protocol.md](R32_post_hoc_audit_protocol.md) | `runs/R32/attempt4` | 48 checks |
| R32 | [R32_post_hoc_audit_result.md](R32_post_hoc_audit_result.md) | `runs/R32/attempt4` | 48 checks |
| R33 | [R33_wan_cost_protocol.md](R33_wan_cost_protocol.md) | `runs/R33/attempt2` | 127 checks |
| R33 | [R33_wan_cost_result.md](R33_wan_cost_result.md) | `runs/R33/attempt2` | 127 checks |
| R34 | [R34_dual_controller_protocol.md](R34_dual_controller_protocol.md) | `runs/R34/attempt1` | 602 checks |
| R34 | [R34_dual_controller_result.md](R34_dual_controller_result.md) | `runs/R34/attempt1` | 602 checks |
| R35 | [R35_same_evidence_baseline_protocol.md](R35_same_evidence_baseline_protocol.md) | `runs/R35/attempt1` | 602 checks |
| R35 | [R35_same_evidence_baseline_result.md](R35_same_evidence_baseline_result.md) | `runs/R35/attempt1` | 602 checks |
| R36 | [R36_frontier_vs_fence_protocol.md](R36_frontier_vs_fence_protocol.md) | `runs/R36/attempt2` | 1,602 checks |
| R36 | [R36_frontier_vs_fence_result.md](R36_frontier_vs_fence_result.md) | `runs/R36/attempt2` | 1,602 checks |
| R38 | [R38_fence_settlement_protocol.md](R38_fence_settlement_protocol.md) | `runs/R38/attempt1` | 1,405 checks |
| R38 | [R38_fence_settlement_result.md](R38_fence_settlement_result.md) | `runs/R38/attempt1` | 1,405 checks |
| R39 | [R39_real_llm_protocol.md](R39_real_llm_protocol.md) | `runs/R39/attempt4` | 431 checks |
| R39 | [R39_real_llm_result.md](R39_real_llm_result.md) | `runs/R39/attempt4` | 431 checks |
| R40 | [R40_intent_change_pause_repair_protocol.md](R40_intent_change_pause_repair_protocol.md) | `runs/R40/attempt2` | 304 checks |
| R40 | [R40_intent_change_pause_repair_result.md](R40_intent_change_pause_repair_result.md) | `runs/R40/attempt2` | 304 checks |
| R41 | [R41_concurrent_model_check_protocol.md](R41_concurrent_model_check_protocol.md) | `runs/R41/attempt1` | 14 checks |
| R41 | [R41_concurrent_model_check_result.md](R41_concurrent_model_check_result.md) | `runs/R41/attempt1` | 14 checks |
| R42 | [R42_unbounded_induction_protocol.md](R42_unbounded_induction_protocol.md) | `runs/R42/attempt1` | 43 checks |
| R42 | [R42_unbounded_induction_result.md](R42_unbounded_induction_result.md) | `runs/R42/attempt1` | 43 checks |
| R43 | [R43_atomix_protocol.md](R43_atomix_protocol.md) | `runs/R43/attempt1` | 62 checks |
| R43 | [R43_atomix_result.md](R43_atomix_result.md) | `runs/R43/attempt1` | 62 checks |
| R44 | [R44_equal_capability_protocol.md](R44_equal_capability_protocol.md) | `runs/R44/attempt1` | 49 checks |
| R44 | [R44_equal_capability_result.md](R44_equal_capability_result.md) | `runs/R44/attempt1` | 49 checks |
| U07 | [U07_clear2_conformance_replay_protocol.md](U07_clear2_conformance_replay_protocol.md) | `runs/U07/attempt1` | 99 checks |
| R45 | [R45_capability_frontier_protocol_20261029.md](R45_capability_frontier_protocol_20261029.md) | `runs/R45/attempt2` | 273 checks |
| R45 | [R45_capability_frontier_result_20261029.md](R45_capability_frontier_result_20261029.md) | `runs/R45/attempt2` | 273 checks |
| R46 | [R46_identity_semantics_protocol_20261029.md](R46_identity_semantics_protocol_20261029.md) | `runs/R46/attempt1` | 111 checks |
| R46 | [R46_identity_semantics_result_20261029.md](R46_identity_semantics_result_20261029.md) | `runs/R46/attempt1` | 111 checks |
| R47 | [R47_task_level_intent_protocol_20261029.md](R47_task_level_intent_protocol_20261029.md) | `runs/R47/attempt1` | 59 checks |
| R47 | [R47_task_level_intent_result_20261029.md](R47_task_level_intent_result_20261029.md) | `runs/R47/attempt1` | 59 checks |
| R48 | [R48_cross_layer_closure_protocol_20261029.md](R48_cross_layer_closure_protocol_20261029.md) | `runs/R48/attempt2` | 13 checks |
| R48 | [R48_cross_layer_closure_result_20261029.md](R48_cross_layer_closure_result_20261029.md) | `runs/R48/attempt2` | 13 checks |
| R49 | [R49_retrofit_cost_protocol_20261029.md](R49_retrofit_cost_protocol_20261029.md) | `runs/R49/attempt2` | 121 checks |
| R49 | [R49_retrofit_cost_result_20261029.md](R49_retrofit_cost_result_20261029.md) | `runs/R49/attempt2` | 121 checks |
