# MEMORIA PLUS P12 — Bitemporalidade completa

- Resultado: **PASS**
- Schema: `memory-0.20.0`
- Contrato: `BT-1.0.0`
- Checks: `42/42`
- Reparos históricos preservados: `5`

## Contrato temporal

- `occurred_at`: tempo real do fato.
- `observed_at`: tempo de conhecimento.
- `valid_from/valid_to`: validade efetiva.
- `created_at`: tempo imutável de persistência.

## Checks

- [x] `api_0_20_0`
- [x] `temporal_spec_requires_auth`
- [x] `temporal_spec_version`
- [x] `five_temporal_dimensions`
- [x] `created_at_not_validity_rule`
- [x] `late_memory_created`
- [x] `late_memory_listed_current`
- [x] `fact_time_preserved_exact`
- [x] `knowledge_time_preserved_exact`
- [x] `validity_start_preserved_exact`
- [x] `persistence_time_independent`
- [x] `transaction_time_before_persistence_hides_late_fact`
- [x] `transaction_time_after_persistence_reveals_late_fact`
- [x] `valid_time_before_fact_hides_memory`
- [x] `context_asof_before_persistence_hides_late_fact`
- [x] `context_asof_after_persistence_reveals_late_fact`
- [x] `closed_interval_memory_created`
- [x] `closed_interval_hidden_now`
- [x] `closed_interval_visible_historically`
- [x] `revision_with_explicit_temporal_envelope`
- [x] `version_fact_time_exact`
- [x] `version_validity_not_derived_from_created_at`
- [x] `naive_timestamp_rejected_422`
- [x] `observed_before_occurred_rejected_422`
- [x] `invalid_validity_interval_rejected_422`
- [x] `late_conversation_ingested`
- [x] `conversation_sidecar_preserves_fact_time`
- [x] `conversation_memory_inherits_same_envelope`
- [x] `conversation_temporal_replay_divergence_rejected`
- [x] `schema_memory_0_20_0`
- [x] `schema_bt_1_0_0`
- [x] `all_temporal_tables_classified`
- [x] `thirty_bitemporal_entities`
- [x] `five_legacy_clock_repairs_preserved`
- [x] `no_invalid_bitemporal_rows`
- [x] `all_bitemporal_insert_triggers_enabled`
- [x] `conversation_sidecar_force_rls`
- [x] `valid_to_valid_until_alias_exact`
- [x] `migration_0027_checksum_exact`
- [x] `sql_observed_before_occurred_rejected`
- [x] `sql_invalid_validity_rejected`
- [x] `temporal_contract_registry_immutable`
