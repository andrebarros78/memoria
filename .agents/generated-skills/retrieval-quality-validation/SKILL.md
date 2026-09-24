---
name: retrieval-quality-validation
description: Evaluate a Memory Permanent retrieval candidate against a versioned golden set and fail closed on relevance, recall, forbidden-memory leakage, scope isolation, temporal validity, or authority regressions. Use before promoting retrieval, ranking, embedding, context-composer, scope, or temporal changes.
---
# Retrieval Quality Validation

## Contract
1. Identify immutable candidate and baseline references.
2. Load a versioned golden set with expected IDs, forbidden IDs, temporal-forbidden IDs, allowed scopes, and allowed authorities.
3. Execute the real MemoryGateway/ContextEngine retrieval path and preserve trace IDs.
4. Compute precision, recall, case pass rate, forbidden hit rate, scope violation rate, temporal violation rate, and authority violation rate.
5. Default fail-closed thresholds: precision >= 0.80, recall >= 0.80, case pass rate = 1.00, and every safety-violation rate = 0.
6. DENY on any forbidden-memory, cross-scope, temporal, or authority violation.
7. Persist evaluation evidence through CanonicalMutationService; quality runs are append-only.
8. Promotion requires PASS plus policy approval. DENY blocks promotion until corrected and retested.
9. Golden-set changes create a new version; evaluation must never silently rewrite its own test set.
10. Re-run after restore/recovery whenever persisted retrieval state is affected.

## Required evidence
- golden_set_id + version + SHA-256
- candidate_ref and baseline_ref
- thresholds
- aggregate metrics
- per-case selected IDs + trace IDs
- explicit PASS/DENY and reasons
- full regression result
- restore/parity result when schema or persisted state changed

## Security invariants
- The agent is read-mostly and does not change memories or ranking.
- No direct database credentials are owned by the agent.
- Tenant/project/mission/session isolation fails closed.
- Persisted payloads pass canonical sanitization.
- Quality evidence is append-only and RLS-protected.