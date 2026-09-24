# MEMORIA-PERMANENTE 0.28.1 - Post-Baseline Attestation

Data: 06/09/2026 - 12h07 - horario de Brasilia

Resultado: **PASS_READY_FOR_COMMIT**

## Governanca de versao

- Versao de software preservada: `0.28.1`.
- Baseline imutavel preservada: `baseline-0.28.1`.
- Nenhum codigo de software foi alterado por esta atestacao.
- Tag funcional prevista: `v5.3-agent-skill-restart-proven-20260906`.

## Evidencia E2E

- Trace de restart: `trace-3f8ea9f2fc3a47c9b7596d9e948dd112`.
- Trace confirmado no PostgreSQL sob tenant `LEGACY`.
- Restart E2E: PASS.
- Resultado da prova: PASS.

## Validacao fresca

- Pytest: 319 passed, 2 skipped, 0 failed.
- Compileall: PASS.
- Migration immutability: PASS.
- PostgreSQL: 51 migrations aplicadas.
- Arquivos de migration: 51/51 correspondentes.
- Missing migrations: 0.
- Checksum mismatches: 0.
- git diff --check: PASS.
- Runtime: V5.3-PRIMARY / v5.3-primary-promoted.

## Decisao

O refresh de evidÃªncia altera apenas o identificador de trace produzido pela verificacao E2E. Por nao alterar comportamento publico, contrato ou codigo do software, nao ha justificativa tecnica para incrementar 0.28.1 para 0.28.2. O evento sera versionado no Git por commit e tag funcional, sem mover a baseline existente.
