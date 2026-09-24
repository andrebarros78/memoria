import pytest

from memory_permanent.domain import (
    HoldType,
    LifecycleState,
    OperatorClass,
    map_operator_class,
)


def test_permanente_creates_sovereign_hold_and_never_purges_directly():
    d = map_operator_class("PERMANENTE")
    assert d.operator_class is OperatorClass.PERMANENTE
    assert d.lifecycle_state is LifecycleState.HOT
    assert d.hold_type is HoldType.SOVEREIGN_HOLD
    assert d.purge_allowed is False


def test_descartavel_only_becomes_delete_eligible():
    d = map_operator_class("DESCARTÁVEL")
    assert d.operator_class is OperatorClass.DESCARTAVEL
    assert d.lifecycle_state is LifecycleState.DELETE_ELIGIBLE
    assert d.hold_type is None
    assert d.purge_allowed is False


def test_descartavel_ascii_alias_is_supported():
    assert map_operator_class("descartavel").operator_class is OperatorClass.DESCARTAVEL


def test_invalid_operator_class_fails_closed():
    with pytest.raises(ValueError):
        map_operator_class("APAGAR_AGORA")
