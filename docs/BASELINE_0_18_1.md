# MEMORIA-PERMANENTE — Baseline 0.18.1

## Escopo

Baseline da MEMORIA PLUS P10: memória formal de decisões e missões.

## Componentes

- API `0.18.1`
- Schema `memory-0.18.1`
- Decision Record `DR-1.1.0`
- Ontologia `KO-1.0.0`
- Experience Graph `EG-1.0.0`
- Causal Policy `CP-1.0.0`
- Migrations `0001–0025` imutáveis

## P10

Decisões críticas são registros soberanos append-only ancorados em sessão/checkpoint, com objetivo, contexto, alternativas, evidências version-bound, rationale, autoridade derivada da identidade autenticada, ação estruturada, expected outcome, actual outcomes e prova. O replay inclui snapshot de missão, ação, evidências e outcomes e produz SHA-256 determinístico.

Novas aplicações que informam `decision_id` devem apontar para decisão formal da mesma missão. Referências textuais legadas foram inventariadas, mas não são aceitas como decisão em novas aplicações. INSERT direto nas tabelas formais é bloqueado fora do boundary canônico.

## Validação

- P10 proof: PASS
- Core: 85/85 PASS
- Adapter: 4/4 PASS
- Audit DAG: PASS
- Backup restore-render: PASS
- Wheel: clean
- P10 Memory Core: PROVEN / VALIDATED

`V4_FULL_PROVEN = NÃO`; prioridades posteriores permanecem pendentes.
