from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from .network_policy import (
    PROVIDER_RESPONSE_MAX_BYTES,
    open_url_no_redirect,
    read_http_response_limited,
    validate_service_base_url,
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ProviderObservation:
    provider: str
    model: str
    external_session_ref: str
    context_sha256: str
    checkpoint_id: str
    required_memory_ids: list[str]
    objective: str
    raw_response_sha256: str
    latency_ms: float
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderAdapter(Protocol):
    provider_id: str

    def probe(self) -> dict[str, Any]: ...

    def observe_context(self, context_pack: dict[str, Any]) -> ProviderObservation: ...


class OpenAIProviderAdapter:
    provider_id = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "gpt-5.6-luna",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = validate_service_base_url(base_url, purpose=f"{self.provider_id} provider")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with open_url_no_redirect(req, timeout=timeout) as response:  # nosec B310 -- URL base is centrally restricted to HTTP(S)

            return json.loads(read_http_response_limited(
                response, max_bytes=PROVIDER_RESPONSE_MAX_BYTES, purpose=f"{self.provider_id} provider"
            ).decode("utf-8"))

    def probe(self) -> dict[str, Any]:
        started = time.perf_counter()
        data = self._request("GET", "/models", timeout=20.0)
        return {
            "provider": self.provider_id,
            "reachable": True,
            "model_count": len(data.get("data", [])),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "paid_inference_used": False,
        }

    @staticmethod
    def _extract_response_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if not parts:
            raise ValueError("OpenAI response did not contain output text")
        return "\n".join(parts)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
        raise ValueError("OpenAI response did not contain a JSON object")

    def observe_context(self, context_pack: dict[str, Any]) -> ProviderObservation:
        if os.getenv("MEMORY_ALLOW_PAID_PROVIDER_PROOF", "0") != "1":
            raise PermissionError(
                "paid OpenAI inference proof is disabled; "
                "set MEMORY_ALLOW_PAID_PROVIDER_PROOF=1 only with explicit authorization"
            )
        context = dict(context_pack.get("context") or {})
        expected_hash = str(context_pack.get("context_sha256") or "")
        checkpoint_id = str(context_pack.get("checkpoint_id") or context.get("checkpoint_id") or "")
        required = sorted(
            str(x)
            for x in (
                context_pack.get("required_memory_ids")
                or context.get("required_memory_ids")
                or []
            )
        )
        objective = str(context.get("objective") or "")
        if not expected_hash or not checkpoint_id or not objective:
            raise ValueError("incomplete Context Pack")
        proof_input = {
            "context_sha256": expected_hash,
            "checkpoint_id": checkpoint_id,
            "required_memory_ids": required,
            "objective": objective,
        }
        prompt = (
            "Validate a sovereign memory context transfer. Return ONLY one JSON object. "
            "Copy the four values exactly from PROOF_INPUT without summarizing or changing them. "
            "Keys: context_sha256, checkpoint_id, required_memory_ids, objective.\n"
            "PROOF_INPUT=" + canonical_json(proof_input)
        )
        started = time.perf_counter()
        raw = self._request(
            "POST",
            "/responses",
            {"model": self.model, "input": prompt, "max_output_tokens": 400},
            timeout=90.0,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        text = self._extract_response_text(raw)
        observed = self._extract_json(text)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ProviderObservation(
            provider=self.provider_id,
            model=self.model,
            external_session_ref=str(raw.get("id") or f"openai:{uuid.uuid4().hex}"),
            context_sha256=str(observed.get("context_sha256") or ""),
            checkpoint_id=str(observed.get("checkpoint_id") or ""),
            required_memory_ids=sorted(str(x) for x in (observed.get("required_memory_ids") or [])),
            objective=str(observed.get("objective") or ""),
            raw_response_sha256=sha256_text(text),
            latency_ms=round(latency_ms, 3),
            metadata={
                "response_id": raw.get("id"),
                "status": raw.get("status"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "paid_inference_used": True,
            },
        )


class OllamaProviderAdapter:
    provider_id = "ollama"

    def __init__(self, model: str = "qwen2.5-coder:3b", *, base_url: str = "http://127.0.0.1:11434") -> None:
        self.model = model
        self.base_url = validate_service_base_url(base_url, purpose=f"{self.provider_id} provider")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 180.0) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with open_url_no_redirect(req, timeout=timeout) as response:  # nosec B310 -- URL base is centrally restricted to HTTP(S)

            return json.loads(read_http_response_limited(
                response, max_bytes=PROVIDER_RESPONSE_MAX_BYTES, purpose=f"{self.provider_id} provider"
            ).decode("utf-8"))

    def probe(self) -> dict[str, Any]:
        started = time.perf_counter()
        data = self._request("GET", "/api/tags", timeout=10.0)
        models = [str(item.get("name")) for item in data.get("models", [])]
        return {
            "provider": self.provider_id,
            "reachable": True,
            "models": models,
            "model_available": self.model in models,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
        raise ValueError("provider response did not contain a JSON object")

    def observe_context(self, context_pack: dict[str, Any]) -> ProviderObservation:
        context = dict(context_pack.get("context") or {})
        expected_hash = str(context_pack.get("context_sha256") or "")
        checkpoint_id = str(context_pack.get("checkpoint_id") or context.get("checkpoint_id") or "")
        required = sorted(str(x) for x in (context_pack.get("required_memory_ids") or context.get("required_memory_ids") or []))
        objective = str(context.get("objective") or "")
        if not expected_hash or not checkpoint_id or not objective:
            raise ValueError("incomplete Context Pack")
        proof_input = {
            "context_sha256": expected_hash,
            "checkpoint_id": checkpoint_id,
            "required_memory_ids": required,
            "objective": objective,
        }
        prompt = (
            "You are validating a sovereign memory context transfer between AI providers. "
            "Return ONLY a JSON object. Copy the four values exactly from PROOF_INPUT. "
            "Do not summarize, translate, alter, or omit them. Keys must be: context_sha256, checkpoint_id, required_memory_ids, objective.\n"
            "PROOF_INPUT=" + canonical_json(proof_input)
        )
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 320},
        }
        raw = self._request("POST", "/api/generate", payload, timeout=240.0)
        latency_ms = (time.perf_counter() - started) * 1000
        text = str(raw.get("response") or "")
        observed = self._extract_json(text)
        return ProviderObservation(
            provider=self.provider_id,
            model=self.model,
            external_session_ref=f"ollama:{self.model}:{uuid.uuid4().hex}",
            context_sha256=str(observed.get("context_sha256") or ""),
            checkpoint_id=str(observed.get("checkpoint_id") or ""),
            required_memory_ids=sorted(str(x) for x in (observed.get("required_memory_ids") or [])),
            objective=str(observed.get("objective") or ""),
            raw_response_sha256=sha256_text(text),
            latency_ms=round(latency_ms, 3),
            metadata={
                "done": bool(raw.get("done")),
                "done_reason": raw.get("done_reason"),
                "eval_count": raw.get("eval_count"),
                "prompt_eval_count": raw.get("prompt_eval_count"),
            },
        )

class LlamaCppProviderAdapter:
    provider_id = "llama.cpp"

    def __init__(self, model: str = "qwen2.5-coder:3b", *, base_url: str = "http://127.0.0.1:11435") -> None:
        self.model = model
        self.base_url = validate_service_base_url(base_url, purpose=f"{self.provider_id} provider")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 180.0) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with open_url_no_redirect(req, timeout=timeout) as response:  # nosec B310 -- URL base is centrally restricted to HTTP(S)

            return json.loads(read_http_response_limited(
                response, max_bytes=PROVIDER_RESPONSE_MAX_BYTES, purpose=f"{self.provider_id} provider"
            ).decode("utf-8"))

    def probe(self) -> dict[str, Any]:
        started = time.perf_counter()
        data = self._request("GET", "/health", timeout=10.0)
        return {
            "provider": self.provider_id,
            "reachable": data.get("status") == "ok",
            "model": self.model,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "credential_required_by_memory": False,
        }

    def observe_context(self, context_pack: dict[str, Any]) -> ProviderObservation:
        context = dict(context_pack.get("context") or {})
        expected_hash = str(context_pack.get("context_sha256") or "")
        checkpoint_id = str(context_pack.get("checkpoint_id") or context.get("checkpoint_id") or "")
        required = sorted(str(x) for x in (context_pack.get("required_memory_ids") or context.get("required_memory_ids") or []))
        objective = str(context.get("objective") or "")
        if not expected_hash or not checkpoint_id or not objective:
            raise ValueError("incomplete Context Pack")
        proof_input = {
            "context_sha256": expected_hash,
            "checkpoint_id": checkpoint_id,
            "required_memory_ids": required,
            "objective": objective,
        }
        prompt = (
            "Validate a sovereign memory context transfer. Return ONLY one JSON object. "
            "Copy the four values exactly from PROOF_INPUT without summarizing, translating or changing them. "
            "Keys: context_sha256, checkpoint_id, required_memory_ids, objective.\n"
            "PROOF_INPUT=" + canonical_json(proof_input)
        )
        started = time.perf_counter()
        raw = self._request("POST", "/v1/chat/completions", {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 400,
        }, timeout=240.0)
        latency_ms = (time.perf_counter() - started) * 1000
        text = str(((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        observed = OllamaProviderAdapter._extract_json(text)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ProviderObservation(
            provider=self.provider_id,
            model=self.model,
            external_session_ref=str(raw.get("id") or f"llamacpp:{uuid.uuid4().hex}"),
            context_sha256=str(observed.get("context_sha256") or ""),
            checkpoint_id=str(observed.get("checkpoint_id") or ""),
            required_memory_ids=sorted(str(x) for x in (observed.get("required_memory_ids") or [])),
            objective=str(observed.get("objective") or ""),
            raw_response_sha256=sha256_text(text),
            latency_ms=round(latency_ms, 3),
            metadata={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "credential_required_by_memory": False,
            },
        )
