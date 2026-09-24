from __future__ import annotations

# Imports below intentionally follow local source-path registration.
# ruff: noqa: E402
import hashlib
import ipaddress
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MEMORY_ROOT = Path(__file__).resolve().parents[1]
MEMORY_SRC = MEMORY_ROOT / "src"
WMCP_ROOT = Path(r"C:\New Projet\WMCP 3.1")
if str(MEMORY_SRC) not in sys.path:
    sys.path.insert(0, str(MEMORY_SRC))
if str(WMCP_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(WMCP_ROOT / "src"))

from windows_mcp.learning_training import (
    InvisibleBrowserAdapter,
    LearningMode,
    LearningTrainingEngine,
)

from memory_permanent.network_policy import validate_service_base_url
from memory_permanent.signed_client import SignedMemoryClient

_CHATGPT_PATH_RE = re.compile(
    r"(?P<path>g/g-p-(?P<project>[A-Za-z0-9._-]{1,200})/c/(?P<conversation>[A-Za-z0-9._-]{1,200}))"
)


def parse_chatgpt_ref(value: str) -> dict[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("unsupported ChatGPT conversation reference")
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or host != "chatgpt.com":
            raise ValueError("ChatGPT conversation URL must use https://chatgpt.com")
        try:
            if parsed.port not in {None, 443}:
                raise ValueError("ChatGPT conversation URL must use the standard HTTPS origin")
        except ValueError as exc:
            raise ValueError("ChatGPT conversation URL has an invalid port") from exc
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError("ChatGPT conversation URL contains unsupported components")
        candidate = parsed.path.lstrip("/")
    else:
        candidate = raw.lstrip("/")
    match = _CHATGPT_PATH_RE.fullmatch(candidate)
    if not match:
        raise ValueError("unsupported ChatGPT conversation reference")
    return {
        "external_session_ref": match.group("path"),
        "project_id": match.group("project"),
        "conversation_id": match.group("conversation"),
    }

def _capture_browser_base_url(value: str) -> str:
    base = validate_service_base_url(value, purpose="ChatGPT capture browser")
    parsed = urlsplit(base)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "chatgpt.com" and parsed.scheme == "https":
        try:
            if parsed.port not in {None, 443}:
                raise ValueError("ChatGPT capture browser must use the standard HTTPS origin")
        except ValueError as exc:
            raise ValueError("ChatGPT capture browser has an invalid port") from exc
        return base
    try:
        if ipaddress.ip_address(host).is_loopback:
            return base
    except ValueError:
        if host == "localhost":
            return base
    raise ValueError("ChatGPT capture browser must target chatgpt.com or loopback test infrastructure")


def _origin(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("ChatGPT capture URL has an invalid port") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
    return parsed.scheme.lower(), host, port


def _capture_target(base_url: str, target: str) -> str:
    value = str(target or "").strip()
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc:
        if value.startswith("//"):
            raise ValueError("ChatGPT capture target must remain origin-relative")
        return value
    if _origin(value) != _origin(base_url):
        raise ValueError("ChatGPT capture target must remain on the configured browser origin")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("ChatGPT capture target contains unsupported URL components")
    return value


def extract_messages(adapter: InvisibleBrowserAdapter) -> list[dict[str, str]]:
    locator = adapter.page.locator("[data-message-author-role]")
    messages: list[dict[str, str]] = []
    for index in range(min(locator.count(), 5000)):
        element = locator.nth(index)
        role = str(element.get_attribute("data-message-author-role") or "unknown").strip().lower()
        text = element.inner_text(timeout=5000).strip()
        if not text:
            continue
        source_id = element.get_attribute("data-message-id")
        if not source_id:
            source_id = hashlib.sha256(f"{index}\0{role}\0{text}".encode()).hexdigest()[:32]
        messages.append({"role": role, "text": text, "message_id": str(source_id)})
    return messages


def capture_chatgpt_conversation(
    conversation_ref: str,
    *,
    memory_api: str = "http://127.0.0.1:8787",
    memory_client_id: str = "chatgpt-capture",
    browser_base_url: str = "https://chatgpt.com/",
    browser_target: str | None = None,
    learning_project_id: str | None = None,
    browser_session_id: str | None = None,
    browser_executable: str | None = None,
) -> dict[str, Any]:
    parsed = parse_chatgpt_ref(conversation_ref)
    browser_base = _capture_browser_base_url(browser_base_url)
    target = _capture_target(browser_base, browser_target or parsed["external_session_ref"])
    memory_client = SignedMemoryClient(memory_api, memory_client_id)
    project = learning_project_id or f"memory-v4-chatgpt-{parsed['conversation_id'][:12]}"
    browser_session = browser_session_id or project
    engine = LearningTrainingEngine.from_path(WMCP_ROOT / ".wmcp31" / "learning_training_v1.sqlite3")
    try:
        engine.create_project(
            project_id=project,
            mode=LearningMode.LEARNING,
            target_type="PLATFORM",
            target_id="chatgpt.com",
            target_version=None,
            objective="Capture and prove ChatGPT conversation recovery into MEMORIA-PERMANENTE V4",
            metadata={"mission": "RECOVERY_BY_CONVERSATION_ID", "memory_core_dependency": False},
        )
        adapter = InvisibleBrowserAdapter(
            base_url=browser_base,
            session_id=browser_session,
            state_root=WMCP_ROOT / ".wmcp31" / "invisible_browser",
            headless=True,
            allow_mutation=False,
            timeout_ms=30_000,
            browser_executable=browser_executable,
        )
        try:
            engine.learn_action_effect(
                project_id=project,
                adapter=adapter,
                objective="Observe and capture authorized conversation read-only",
                branch="conversation-capture",
                start_target=None,
                action={"kind": "navigate", "target": target},
                expected=None,
            )
            observation = adapter.observe()
            messages = extract_messages(adapter)
            base = {
                "conversation_id": parsed["conversation_id"],
                "project_id": parsed["project_id"],
                "final_url": observation.state.get("url"),
                "http_status": observation.state.get("status_code"),
                "title": observation.state.get("title"),
                "message_count": len(messages),
                "operator_interference": adapter.operator_interference,
                "operator_desktop_used": adapter.resource_state.get("operator_desktop_used"),
                "personal_browser_used": adapter.resource_state.get("personal_browser_used"),
                "learning_project_id": project,
            }
            status_code = int(observation.state.get("status_code") or 0)
            if status_code == 403:
                return {**base, "status": "EXTERNAL_SOURCE_BLOCKED_403", "captured": False, "recoverable": False}
            if status_code >= 400:
                return {**base, "status": "EXTERNAL_SOURCE_ERROR", "captured": False, "recoverable": False}
            if not messages:
                return {**base, "status": "NO_MESSAGES_VISIBLE", "captured": False, "recoverable": False}
            payload = {
                "provider": "chatgpt",
                "external_session_ref": parsed["external_session_ref"],
                "objective": str(
                    observation.state.get("title") or f"Recovered ChatGPT conversation {parsed['conversation_id']}"
                ),
                "project_id": parsed["project_id"],
                "capture_source": "INVISIBLE_BROWSER_LEARNING",
                "messages": messages,
            }
            memory_status, captured = memory_client.request(
                "POST",
                "/v1/external-sessions/capture",
                payload,
                extra_headers={"X-Memory-Project": parsed["project_id"]},
                timeout=15,
            )
            if memory_status >= 400:
                detail = captured.get("detail") if isinstance(captured, dict) else str(captured)
                raise RuntimeError(f"memory API HTTP {memory_status}: {str(detail)[:500]}")
            if not isinstance(captured, dict):
                raise RuntimeError("memory API returned a non-object capture response")
            return {
                **base,
                "status": "CAPTURED",
                "captured": True,
                "recoverable": bool(captured.get("recoverable")),
                "memory": captured,
            }
        finally:
            adapter.close()
    finally:
        engine.close()
