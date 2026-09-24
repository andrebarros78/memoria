from __future__ import annotations

import pytest
from pydantic import ValidationError

from memory_permanent.api import (
    KnowledgeRelationRequest,
    OntologyTransitionRequest,
    RememberRequest,
)
from memory_permanent.client_auth import required_permission_for_path
from memory_permanent.ontology import (
    RELATION_RULES,
    TRANSITION_RULES,
    KnowledgeType,
    ontology_spec,
    validate_relation,
    validate_transition,
)


def test_canonical_knowledge_types_are_exact() -> None:
    assert [x.value for x in KnowledgeType] == [
        "FACT", "HYPOTHESIS", "EVIDENCE", "OBSERVATION", "INFERENCE",
        "CORRELATION", "CAUSE", "PROCEDURE", "DECISION", "INTERVENTION",
        "OUTCOME", "EXPERIMENT", "LEARNING", "CONSTRAINT", "OBJECTIVE",
    ]


def test_remember_request_rejects_free_text_category() -> None:
    with pytest.raises(ValidationError):
        RememberRequest(
            namespace="TEST", memory_key="bad", category="MAGIC",
            content={"x": 1}, content_text="x", provenance={"proof": "test"},
            confidence=1.0, source="test",
        )


def test_valid_relation_and_transition_are_domain_accepted() -> None:
    src, rel, dst = validate_relation("EVIDENCE", "SUPPORTS", "HYPOTHESIS")
    assert (src, rel, dst) in RELATION_RULES
    assert validate_transition("HYPOTHESIS", "FACT") in TRANSITION_RULES


def test_invalid_relation_and_transition_are_domain_rejected() -> None:
    with pytest.raises(ValueError, match="invalid ontology relation"):
        validate_relation("PROCEDURE", "CAUSES", "HYPOTHESIS")
    with pytest.raises(ValueError, match="invalid ontology transition"):
        validate_transition("FACT", "HYPOTHESIS")


def test_api_models_reject_unknown_relation_and_transition_type() -> None:
    with pytest.raises(ValidationError):
        KnowledgeRelationRequest(from_item_id="mem-a", relation_type="MAGIC", to_item_id="mem-b")
    with pytest.raises(ValidationError):
        OntologyTransitionRequest(to_category="MAGIC", reason="invalid")


def test_ontology_spec_and_permissions_are_versioned_and_least_privilege() -> None:
    spec = ontology_spec()
    assert spec["version"] == "KO-1.0.0"
    assert len(spec["knowledge_types"]) == 15
    assert len(spec["relation_rules"]) == 96
    assert len(spec["transition_rules"]) == 7
    assert required_permission_for_path("/v1/ontology", "GET") == "memory:read"
    assert required_permission_for_path("/v1/knowledge-relations", "GET") == "memory:read"
    assert required_permission_for_path("/v1/knowledge-relations", "POST") == "memory:write"
