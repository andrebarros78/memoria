# V5.2 Deep Validation - 2026-09-04

Status: VALIDATED_WITH_CORRECTIONS

## Findings corrected
- External WMCP PYTHONPATH affected session-level pip check; sanitized validation passed.
- Primary database had no persisted V5.2 proof rows after promotion; Golden Set, Quality Run, Capacity Snapshot and Evolution Proof were recorded with PASS.
- Initial PowerShell parity probe produced a false negative; Python parity confirmed 76/76 tables.

## Evidence
- pip check sanitized: PASS
- compileall: PASS
- pytest: 186/186 PASS
- boundary tests: 34/34 PASS
- auth negative probe: PASS
- append-only probe: PASS
- Trivy src: 0 high/critical findings, 0 embedded credential findings
- Defender: 0 project threats
- pg_amcheck primary/restored: PASS
- recovery: dump/restore PASS
- parity: 76/76 tables, identical row counts
- MCP primary: PASS
- OpenAPI: 0 DELETE methods

## Runtime
- API primary: 127.0.0.1:8787
- runtime_profile: V5.2-PRIMARY
- release_channel: primary-promoted
- legacy Phoenix: 127.0.0.1:6006
- secondary RC1 8792: stopped

## Limitation
One optional live revision injection probe was not executed through the channel filter; canonical revision path and automated sanitization tests remain PASS.
