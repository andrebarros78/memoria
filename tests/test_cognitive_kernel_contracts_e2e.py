import subprocess
import sys

from memory_permanent.api import app


def test_f01_does_not_publish_cognitive_api_before_later_gates():
    assert not any(path.startswith("/v1/cognitive") for path in app.openapi()["paths"])


def test_f01_fresh_interpreter_restart_smoke_and_behavior_isolation():
    code = r'''
from memory_permanent.api import app
before = tuple(sorted(app.openapi()["paths"]))
from memory_permanent.cognitive_contracts import CognitiveEnvelope, CognitiveScope, CognitiveSignalType
from memory_permanent.cognitive_policy import CognitivePolicyContext, evaluate_cognitive_envelope
env = CognitiveEnvelope(CognitiveSignalType.ACTIVATION, CognitiveScope("t1", "u1"), "memory:m1")
assert evaluate_cognitive_envelope(env, CognitivePolicyContext("t1", "u1")).accepted
assert not evaluate_cognitive_envelope(env, CognitivePolicyContext("t2", "u1")).accepted
after = tuple(sorted(app.openapi()["paths"]))
assert before == after
'''
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
