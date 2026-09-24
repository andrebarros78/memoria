# Disaster Recovery Migration Attestations — 0.26.1-recovery

The historical migration bytes below were physically lost during the filesystem incident and are NOT recreated under their historical filenames.

- `0031_restore_hardening_causal_function.sql` historical SHA-256: `f3f513fd1ddb6f0e0c911e4a32f05f62a41361fcf1f31ef388df411445bbf371`
- `0033_lifecycle_manager_m12.sql` historical SHA-256: `0e0f50aa9e99642cc12390c5d22e1e819469228bb19d545f6b9a7398b9a39337`

Recovery equivalents:

- `0030z_recovery_equivalent_historical_0031.sql`
- `0032z_recovery_equivalent_historical_0033.sql`

These files assert semantic reconstruction only. They do not claim byte identity or cryptographic continuity with the lost files.
