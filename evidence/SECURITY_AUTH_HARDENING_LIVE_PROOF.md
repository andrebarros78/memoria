# SECURITY AUTH HARDENING LIVE PROOF

Result: **PASS**

Auth scheme: `MEMORY-HMAC-SHA256-V1`

| Check | Actual | Expected | Result |
|---|---:|---:|---|
| public_health | 200 | 200 | PASS |
| unsigned_general_rejected | 401 | 401 | PASS |
| unsigned_identity_spoof_rejected | 401 | 401 | PASS |
| signed_admin_allowed | 200 | 200 | PASS |
| tampered_signature_rejected | 401 | 401 | PASS |
| tampered_body_rejected | 401 | 401 | PASS |
| replay_first_request_allowed | 200 | 200 | PASS |
| replay_second_request_rejected | 401 | 401 | PASS |
| capture_client_ingest_allowed | 201 | 201 | PASS |
| capture_client_admin_denied | 403 | 403 | PASS |
| capture_client_tenant_spoof_denied | 403 | 403 | PASS |
| stale_timestamp_rejected | 401 | 401 | PASS |
