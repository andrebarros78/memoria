# MEMORIA PLUS P09 — Prova de memória causal

- Resultado: **PASS**
- API: `0.17.0`
- Schema: `memory-0.17.0`
- Política causal: `CP-1.0.0`
- Assessment forte elegível: `True`
- Promoção: `CORRELATION -> CAUSE`
- Checks: `36/36`

## Garantias provadas

- sucesso/expected/actual isolados não promovem CAUSE;
- criação direta de CAUSE é rejeitada;
- transição ontológica genérica para CAUSE é rejeitada;
- assessment causal exige hipótese, intervenção, comparator/control, confounders, mecanismo, counterfactual, attribution confidence, sample size, repetição e evidência independente;
- decisão de elegibilidade é idêntica no domínio Python e no PostgreSQL;
- assessment é preso à versão/hash atual e se torna inutilizável após revisão;
- promoção invalida validação/governor eligibility;
- assessments e promotions são append-only e protegidos por FORCE RLS.