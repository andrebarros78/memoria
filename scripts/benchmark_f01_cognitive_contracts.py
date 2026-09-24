from __future__ import annotations

import json
from time import perf_counter

from memory_permanent.cognitive_contracts import (
    CognitiveEnvelope,
    CognitiveScope,
    CognitiveSignalType,
)
from memory_permanent.cognitive_policy import (
    CognitivePolicyContext,
    evaluate_cognitive_envelope,
)


def main(iterations: int = 100_000) -> None:
    envelope = CognitiveEnvelope(
        CognitiveSignalType.ACTIVATION,
        CognitiveScope("bench", "owner"),
        "memory:bench",
    )
    context = CognitivePolicyContext("bench", "owner")
    started = perf_counter()
    accepted = 0
    for _ in range(iterations):
        accepted += int(evaluate_cognitive_envelope(envelope, context).accepted)
    elapsed = perf_counter() - started
    print(
        json.dumps(
            {
                "phase": "F01",
                "benchmark": "cognitive_policy_evaluation",
                "iterations": iterations,
                "accepted": accepted,
                "elapsed_seconds": elapsed,
                "operations_per_second": iterations / elapsed if elapsed else None,
                "microseconds_per_operation": (elapsed / iterations) * 1_000_000 if iterations else None,
                "threshold": None,
                "purpose": "baseline measurement only; F01 defines no performance gate",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
