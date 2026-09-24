from datetime import UTC, datetime

from memory_permanent.store import idempotency_temporal_request, sha256_json


def test_omitted_server_temporal_defaults_are_stable_for_idempotency():
    a=idempotency_temporal_request(occurred_at=None,observed_at=None,valid_from=None,valid_to=None)
    b=idempotency_temporal_request(occurred_at=None,observed_at=None,valid_from=None,valid_to=None)
    assert a == {"occurred_at":None,"observed_at":None,"valid_from":None,"valid_to":None}
    assert sha256_json(a)==sha256_json(b)

def test_explicit_temporal_request_is_hash_bound():
    t=datetime(2026,9,4,22,45,tzinfo=UTC)
    a=idempotency_temporal_request(occurred_at=t,observed_at=None,valid_from=t,valid_to=None)
    b=idempotency_temporal_request(occurred_at=t,observed_at=None,valid_from=t,valid_to=None)
    c=idempotency_temporal_request(occurred_at=t,observed_at=t,valid_from=t,valid_to=None)
    assert a==b
    assert sha256_json(a)==sha256_json(b)
    assert sha256_json(a)!=sha256_json(c)
