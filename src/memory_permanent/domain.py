from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OperatorClass(StrEnum):
    PERMANENTE = "PERMANENTE"
    ATIVA = "ATIVA"
    ARQUIVADA = "ARQUIVADA"
    DESCARTAVEL = "DESCARTÁVEL"
    PROTEGIDA = "PROTEGIDA"


class LifecycleState(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    DELETE_ELIGIBLE = "DELETE_ELIGIBLE"
    QUARANTINED = "QUARANTINED"
    PURGED = "PURGED"


class HoldType(StrEnum):
    SOVEREIGN_HOLD = "SOVEREIGN_HOLD"
    AUDIT_HOLD = "AUDIT_HOLD"
    EVIDENCE_HOLD = "EVIDENCE_HOLD"
    INCIDENT_HOLD = "INCIDENT_HOLD"
    LEGAL_HOLD = "LEGAL_HOLD"


@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    operator_class: OperatorClass
    lifecycle_state: LifecycleState
    hold_type: HoldType | None = None
    purge_allowed: bool = False


def map_operator_class(value: str) -> ClassificationDecision:
    normalized = value.strip().upper().replace("DESCARTAVEL", "DESCARTÁVEL")
    operator_class = OperatorClass(normalized)
    if operator_class is OperatorClass.PERMANENTE:
        return ClassificationDecision(operator_class, LifecycleState.HOT, HoldType.SOVEREIGN_HOLD, False)
    if operator_class is OperatorClass.ATIVA:
        return ClassificationDecision(operator_class, LifecycleState.HOT, None, False)
    if operator_class is OperatorClass.ARQUIVADA:
        return ClassificationDecision(operator_class, LifecycleState.COLD, None, False)
    if operator_class is OperatorClass.DESCARTAVEL:
        return ClassificationDecision(operator_class, LifecycleState.DELETE_ELIGIBLE, None, False)
    if operator_class is OperatorClass.PROTEGIDA:
        return ClassificationDecision(operator_class, LifecycleState.HOT, HoldType.EVIDENCE_HOLD, False)
    raise ValueError(f"classificação não suportada: {value}")
