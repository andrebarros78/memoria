# MEMORIA PLUS P07 PROOF

**Result:** PASS

- API: 0.15.2
- Schema: memory-0.15.2
- Ontology: KO-1.0.0
- Knowledge types: 15
- Relation rules: 96
- Transition rules: 7
- Legacy rows normalized with ledger: 617

## Checks
- api_0_15_2: PASS
- ontology_requires_auth: PASS
- ontology_api_version: PASS
- exact_15_types: PASS
- invalid_category_api_422: PASS
- valid_relation_api_201: PASS
- invalid_relation_api_422: PASS
- valid_transition_api_200: PASS
- invalid_transition_api_422: PASS
- relation_snapshot_preserved_after_transition: PASS
- relation_stale_on_category_transition: PASS
- relation_stale_on_source_revision: PASS
- transition_invalidates_validation: PASS
- transition_ledger_exact: PASS
- relation_state_events_recorded: PASS
- schema_invalid_category_rejected: PASS
- schema_invalid_relation_rejected: PASS
- schema_direct_category_update_rejected: PASS
- schema_invalid_transition_rejected: PASS
- ontology_rules_immutable: PASS
- domain_db_relation_rules_identical: PASS
- domain_db_transition_rules_identical: PASS
- legacy_categories_migrated: PASS
- all_persisted_categories_canonical: PASS
- category_check_constraint_present: PASS
- ontology_tables_force_rls: PASS
- schema_version: PASS
- ontology_schema_version: PASS
