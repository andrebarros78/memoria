from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class KnowledgeType(StrEnum):
    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    CORRELATION = "CORRELATION"
    CAUSE = "CAUSE"
    PROCEDURE = "PROCEDURE"
    DECISION = "DECISION"
    INTERVENTION = "INTERVENTION"
    OUTCOME = "OUTCOME"
    EXPERIMENT = "EXPERIMENT"
    LEARNING = "LEARNING"
    CONSTRAINT = "CONSTRAINT"
    OBJECTIVE = "OBJECTIVE"


class KnowledgeRelationType(StrEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    DERIVED_FROM = "DERIVED_FROM"
    CORRELATES_WITH = "CORRELATES_WITH"
    CAUSES = "CAUSES"
    TESTS = "TESTS"
    PRODUCES = "PRODUCES"
    IMPLEMENTS = "IMPLEMENTS"
    CONSTRAINS = "CONSTRAINS"
    ADVANCES = "ADVANCES"
    BASED_ON = "BASED_ON"


LEGACY_CATEGORY_MAP: dict[str, KnowledgeType] = {
    "EVENT": KnowledgeType.OBSERVATION,
    "REQUIREMENT": KnowledgeType.CONSTRAINT,
    "RULE": KnowledgeType.CONSTRAINT,
    "DOCUMENT": KnowledgeType.EVIDENCE,
    "STATE": KnowledgeType.OBSERVATION,
}


def _rules(relation: KnowledgeRelationType, source: KnowledgeType, targets: Iterable[KnowledgeType]):
    return {(source, relation, target) for target in targets}


RELATION_RULES = frozenset().union(
    _rules(KnowledgeRelationType.SUPPORTS, KnowledgeType.EVIDENCE, [KnowledgeType.FACT, KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE, KnowledgeType.CORRELATION, KnowledgeType.CAUSE, KnowledgeType.LEARNING, KnowledgeType.DECISION]),
    _rules(KnowledgeRelationType.SUPPORTS, KnowledgeType.OBSERVATION, [KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE, KnowledgeType.CORRELATION]),
    _rules(KnowledgeRelationType.SUPPORTS, KnowledgeType.FACT, [KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE, KnowledgeType.DECISION, KnowledgeType.PROCEDURE]),
    _rules(KnowledgeRelationType.SUPPORTS, KnowledgeType.OUTCOME, [KnowledgeType.LEARNING, KnowledgeType.PROCEDURE]),
    _rules(KnowledgeRelationType.SUPPORTS, KnowledgeType.LEARNING, [KnowledgeType.DECISION, KnowledgeType.PROCEDURE, KnowledgeType.EXPERIMENT]),
    _rules(KnowledgeRelationType.REFUTES, KnowledgeType.EVIDENCE, [KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE, KnowledgeType.CORRELATION, KnowledgeType.CAUSE]),
    _rules(KnowledgeRelationType.REFUTES, KnowledgeType.OBSERVATION, [KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE, KnowledgeType.CORRELATION]),
    _rules(KnowledgeRelationType.REFUTES, KnowledgeType.FACT, [KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE]),
    _rules(KnowledgeRelationType.REFUTES, KnowledgeType.OUTCOME, [KnowledgeType.HYPOTHESIS, KnowledgeType.CAUSE, KnowledgeType.PROCEDURE]),
    _rules(KnowledgeRelationType.DERIVED_FROM, KnowledgeType.INFERENCE, [KnowledgeType.OBSERVATION, KnowledgeType.EVIDENCE, KnowledgeType.FACT]),
    _rules(KnowledgeRelationType.DERIVED_FROM, KnowledgeType.CORRELATION, [KnowledgeType.OBSERVATION, KnowledgeType.EVIDENCE, KnowledgeType.FACT]),
    _rules(KnowledgeRelationType.DERIVED_FROM, KnowledgeType.CAUSE, [KnowledgeType.EVIDENCE, KnowledgeType.EXPERIMENT, KnowledgeType.OUTCOME, KnowledgeType.OBSERVATION]),
    _rules(KnowledgeRelationType.DERIVED_FROM, KnowledgeType.LEARNING, [KnowledgeType.OUTCOME, KnowledgeType.EXPERIMENT, KnowledgeType.EVIDENCE, KnowledgeType.FACT]),
    _rules(KnowledgeRelationType.DERIVED_FROM, KnowledgeType.PROCEDURE, [KnowledgeType.LEARNING, KnowledgeType.EVIDENCE]),
    _rules(KnowledgeRelationType.DERIVED_FROM, KnowledgeType.DECISION, [KnowledgeType.FACT, KnowledgeType.EVIDENCE, KnowledgeType.LEARNING, KnowledgeType.CONSTRAINT, KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.CORRELATES_WITH, KnowledgeType.CORRELATION, [KnowledgeType.OBSERVATION, KnowledgeType.FACT, KnowledgeType.EVIDENCE]),
    _rules(KnowledgeRelationType.CAUSES, KnowledgeType.CAUSE, [KnowledgeType.OUTCOME, KnowledgeType.OBSERVATION]),
    _rules(KnowledgeRelationType.TESTS, KnowledgeType.EXPERIMENT, [KnowledgeType.HYPOTHESIS, KnowledgeType.CORRELATION, KnowledgeType.CAUSE, KnowledgeType.PROCEDURE]),
    _rules(KnowledgeRelationType.PRODUCES, KnowledgeType.EXPERIMENT, [KnowledgeType.OUTCOME, KnowledgeType.EVIDENCE]),
    _rules(KnowledgeRelationType.PRODUCES, KnowledgeType.INTERVENTION, [KnowledgeType.OUTCOME, KnowledgeType.OBSERVATION]),
    _rules(KnowledgeRelationType.PRODUCES, KnowledgeType.PROCEDURE, [KnowledgeType.OUTCOME]),
    _rules(KnowledgeRelationType.IMPLEMENTS, KnowledgeType.INTERVENTION, [KnowledgeType.DECISION, KnowledgeType.PROCEDURE]),
    _rules(KnowledgeRelationType.CONSTRAINS, KnowledgeType.CONSTRAINT, [KnowledgeType.OBJECTIVE, KnowledgeType.DECISION, KnowledgeType.PROCEDURE, KnowledgeType.INTERVENTION, KnowledgeType.EXPERIMENT]),
    _rules(KnowledgeRelationType.ADVANCES, KnowledgeType.DECISION, [KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.ADVANCES, KnowledgeType.INTERVENTION, [KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.ADVANCES, KnowledgeType.PROCEDURE, [KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.ADVANCES, KnowledgeType.EXPERIMENT, [KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.ADVANCES, KnowledgeType.LEARNING, [KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.BASED_ON, KnowledgeType.DECISION, [KnowledgeType.FACT, KnowledgeType.EVIDENCE, KnowledgeType.LEARNING, KnowledgeType.CONSTRAINT, KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.BASED_ON, KnowledgeType.PROCEDURE, [KnowledgeType.FACT, KnowledgeType.EVIDENCE, KnowledgeType.LEARNING, KnowledgeType.CONSTRAINT]),
    _rules(KnowledgeRelationType.BASED_ON, KnowledgeType.INTERVENTION, [KnowledgeType.DECISION, KnowledgeType.PROCEDURE, KnowledgeType.CONSTRAINT, KnowledgeType.OBJECTIVE]),
    _rules(KnowledgeRelationType.BASED_ON, KnowledgeType.EXPERIMENT, [KnowledgeType.HYPOTHESIS, KnowledgeType.CORRELATION, KnowledgeType.CAUSE, KnowledgeType.CONSTRAINT, KnowledgeType.OBJECTIVE]),
)

TRANSITION_RULES = frozenset({
    (KnowledgeType.OBSERVATION, KnowledgeType.EVIDENCE),
    (KnowledgeType.EVIDENCE, KnowledgeType.FACT),
    (KnowledgeType.HYPOTHESIS, KnowledgeType.INFERENCE),
    (KnowledgeType.HYPOTHESIS, KnowledgeType.FACT),
    (KnowledgeType.INFERENCE, KnowledgeType.FACT),
    (KnowledgeType.CORRELATION, KnowledgeType.CAUSE),
    (KnowledgeType.OUTCOME, KnowledgeType.LEARNING),
})


def normalize_knowledge_type(value: str | KnowledgeType) -> KnowledgeType:
    if isinstance(value, KnowledgeType):
        return value
    return KnowledgeType(str(value).strip().upper())


def normalize_relation_type(value: str | KnowledgeRelationType) -> KnowledgeRelationType:
    if isinstance(value, KnowledgeRelationType):
        return value
    return KnowledgeRelationType(str(value).strip().upper())


def validate_relation(source: str | KnowledgeType, relation: str | KnowledgeRelationType, target: str | KnowledgeType) -> tuple[KnowledgeType, KnowledgeRelationType, KnowledgeType]:
    src = normalize_knowledge_type(source)
    rel = normalize_relation_type(relation)
    dst = normalize_knowledge_type(target)
    if (src, rel, dst) not in RELATION_RULES:
        raise ValueError(f"invalid ontology relation: {src.value} {rel.value} {dst.value}")
    return src, rel, dst


def validate_transition(source: str | KnowledgeType, target: str | KnowledgeType) -> tuple[KnowledgeType, KnowledgeType]:
    src = normalize_knowledge_type(source)
    dst = normalize_knowledge_type(target)
    if (src, dst) not in TRANSITION_RULES:
        raise ValueError(f"invalid ontology transition: {src.value} -> {dst.value}")
    return src, dst


def ontology_spec() -> dict[str, object]:
    return {
        "version": "KO-1.0.0",
        "knowledge_types": [x.value for x in KnowledgeType],
        "relation_types": [x.value for x in KnowledgeRelationType],
        "relation_rules": [
            {"source": a.value, "relation": b.value, "target": c.value}
            for a, b, c in sorted(RELATION_RULES, key=lambda x: (x[0].value, x[1].value, x[2].value))
        ],
        "transition_rules": [
            {"from": a.value, "to": b.value}
            for a, b in sorted(TRANSITION_RULES, key=lambda x: (x[0].value, x[1].value))
        ],
        "legacy_category_map": {k: v.value for k, v in sorted(LEGACY_CATEGORY_MAP.items())},
    }
