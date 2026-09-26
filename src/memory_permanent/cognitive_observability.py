from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore, Condition, Lock
from time import monotonic
from types import MappingProxyType
from typing import Any

COGNITIVE_OBSERVABILITY_VERSION = "COBS-1.2.0"
_ALLOWED_METRICS = frozenset(
    {
        "memory_activation_total",
        "priming_events_total",
        "salience_computations_total",
        "association_traversals_total",
        "consolidation_runs_total",
        "consolidation_candidates_total",
        "cognitive_shadow_failures_total",
        "cognitive_shadow_dropped_total",
    }
)


class CognitiveMetrics:
    """In-process shadow metrics. No memory content or identifiers are recorded."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in _ALLOWED_METRICS:
            raise ValueError("unknown cognitive metric")
        value = int(amount)
        if value < 1 or value > 1_000_000:
            raise ValueError("metric increment out of bounds")
        with self._lock:
            self._counts[name] += value

    def snapshot(self) -> Mapping[str, int]:
        with self._lock:
            values = {name: int(self._counts.get(name, 0)) for name in sorted(_ALLOWED_METRICS)}
        return MappingProxyType(values)

    def reset_for_test(self) -> None:
        with self._lock:
            self._counts.clear()


metrics = CognitiveMetrics()


class CognitiveShadowDispatcher:
    """Bounded non-blocking dispatcher so shadow cognition cannot stall core traffic."""

    def __init__(self, *, max_workers: int = 2, max_in_flight: int = 256) -> None:
        workers = int(max_workers)
        capacity = int(max_in_flight)
        if not 1 <= workers <= 16:
            raise ValueError("max_workers out of bounds")
        if not 1 <= capacity <= 100_000:
            raise ValueError("max_in_flight out of bounds")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="memory-cognitive-shadow")
        self._slots = BoundedSemaphore(capacity)
        self._condition = Condition()
        self._in_flight = 0

    def _done(self, future: Future[Any]) -> None:
        try:
            if future.exception() is not None:
                metrics.increment("cognitive_shadow_failures_total")
        finally:
            self._slots.release()
            with self._condition:
                self._in_flight -= 1
                self._condition.notify_all()

    def submit(self, function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> bool:
        if not self._slots.acquire(blocking=False):
            metrics.increment("cognitive_shadow_dropped_total")
            return False
        with self._condition:
            self._in_flight += 1
        try:
            future = self._executor.submit(function, *args, **kwargs)
        except RuntimeError:
            self._slots.release()
            with self._condition:
                self._in_flight -= 1
                self._condition.notify_all()
            metrics.increment("cognitive_shadow_failures_total")
            return False
        future.add_done_callback(self._done)
        return True

    def wait_for_idle(self, timeout: float = 10.0) -> bool:
        deadline = monotonic() + max(float(timeout), 0.0)
        with self._condition:
            while self._in_flight:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True


dispatcher = CognitiveShadowDispatcher()


def cognitive_observability_spec() -> dict[str, object]:
    return {
        "version": COGNITIVE_OBSERVABILITY_VERSION,
        "mode": "SHADOW",
        "dispatch": "BOUNDED_ASYNC",
        "max_in_flight": 256,
        "metrics": sorted(_ALLOWED_METRICS),
        "contains_memory_content": False,
        "contains_memory_identifiers": False,
    }
