from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import HTTPException, Request

from .secret_sanitizer import platform_key_provider

_AUTH_WINDOW_SECONDS = 90
MEMORY_API_REQUEST_MAX_BYTES = 32 * 1024 * 1024
CLIENT_AUTH_ENTROPY = b"MEMORIA-PERMANENTE:CLIENT-AUTH:V1"
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_NONCE_RE = re.compile(r"^[A-Fa-f0-9]{32,128}$")


def validate_client_id(client_id: str) -> str:
    """Validate one client id before registry or credential-path use."""
    value = str(client_id or "").strip()
    if not _CLIENT_ID_RE.fullmatch(value):
        raise ValueError("invalid Memory API client id")
    return value

def _state_int(value: object, detail: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise HTTPException(status_code=503, detail=detail)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=detail) from exc


def auth_root() -> Path:
    configured = os.getenv("MEMORY_AUTH_ROOT", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        program_data = os.getenv("ProgramData", r"C:\ProgramData")
        return Path(program_data) / "MemoriaPermanente" / "auth"
    return Path("/var/lib/memoria-permanente/auth")


@dataclass(frozen=True, slots=True)
class ClientPrincipal:
    client_id: str
    permissions: frozenset[str]
    tenants: frozenset[str]
    agents: frozenset[str]
    users: frozenset[str]
    projects: frozenset[str]
    teams: frozenset[str]
    organizations: frozenset[str]
    default_tenant: str | None = None
    default_agent: str | None = None
    default_user: str | None = None
    default_project: str | None = None
    default_team: str | None = None
    default_organization: str | None = None

    def allows_permission(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions or any(
            p.endswith(":*") and permission.startswith(p[:-1]) for p in self.permissions
        )

    @staticmethod
    def _resolve(allowed: frozenset[str], requested: str | None, default: str | None, field: str) -> str | None:
        value = (requested or default or "").strip()
        if not value:
            return None
        if "*" not in allowed and value not in allowed:
            raise HTTPException(status_code=403, detail=f"client is not authorized for {field}")
        return value

    def resolve_claims(
        self,
        *,
        tenant: str | None,
        agent: str | None,
        user: str | None,
        project: str | None,
        team: str | None,
        organization: str | None,
    ) -> dict[str, str | None]:
        tenant_value = self._resolve(self.tenants, (tenant or "").strip().upper() or None,
                                     (self.default_tenant or "").strip().upper() or None, "tenant")
        if not tenant_value:
            raise HTTPException(status_code=403, detail="authenticated client has no tenant scope")
        agent_value = self._resolve(self.agents, agent, self.default_agent, "agent")
        if tenant_value == "__SYSTEM__" or (agent_value or "").strip().upper() == "__SYSTEM__":
            raise HTTPException(status_code=403, detail="reserved system context is not available to API clients")
        return {
            "tenant": tenant_value,
            "agent": agent_value,
            "user": self._resolve(self.users, user, self.default_user, "user"),
            "project": self._resolve(self.projects, project, self.default_project, "project"),
            "team": self._resolve(self.teams, team, self.default_team, "team"),
            "organization": self._resolve(self.organizations, organization, self.default_organization, "organization"),
        }


class ClientRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else auth_root()
        self.registry_path = self.root / "clients.json"

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail="Memory API client registry is not provisioned") from exc
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=503, detail="Memory API client registry is unreadable") from exc
        if int(data.get("version", 0)) != 1 or not isinstance(data.get("clients"), dict):
            raise HTTPException(status_code=503, detail="Memory API client registry is invalid")
        return data

    def get(self, client_id: str) -> tuple[ClientPrincipal, bytes]:
        try:
            client_id = validate_client_id(client_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="invalid client id") from exc
        data = self._load()
        row = data["clients"].get(client_id)
        if not isinstance(row, dict) or row.get("status") != "ACTIVE":
            raise HTTPException(status_code=401, detail="unknown or inactive client")
        secret_rel = str(row.get("secret_file") or "")
        secret_path = (self.root / secret_rel).resolve()
        root_resolved = self.root.resolve()
        if root_resolved not in secret_path.parents:
            raise HTTPException(status_code=503, detail="client registry secret path is invalid")
        secret = platform_key_provider(secret_path, machine_scope=True, entropy=CLIENT_AUTH_ENTROPY).load_or_create()
        principal = ClientPrincipal(
            client_id=client_id,
            permissions=frozenset(map(str, row.get("permissions") or [])),
            tenants=frozenset(map(str, row.get("tenants") or [])),
            agents=frozenset(map(str, row.get("agents") or [])),
            users=frozenset(map(str, row.get("users") or [])),
            projects=frozenset(map(str, row.get("projects") or [])),
            teams=frozenset(map(str, row.get("teams") or [])),
            organizations=frozenset(map(str, row.get("organizations") or [])),
            default_tenant=row.get("default_tenant"),
            default_agent=row.get("default_agent"),
            default_user=row.get("default_user"),
            default_project=row.get("default_project"),
            default_team=row.get("default_team"),
            default_organization=row.get("default_organization"),
        )
        return principal, secret


@contextmanager
def _exclusive_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    with path.open("a+b") as fh:
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
        try:
            yield
        finally:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


BROWSER_SESSION_PERMISSIONS = frozenset({"memory:read", "memory:admin"})


class BrowserSessionRegistry:
    """Short-lived, least-privilege bearer sessions for the loopback operator UI.

    Long-lived HMAC client keys never enter browser storage. Only SHA-256 token
    digests are persisted, and browser sessions cannot mint new sessions or purge.
    """

    def __init__(self, state_path: Path | None = None, max_sessions: int = 64) -> None:
        self.state_path = Path(state_path) if state_path is not None else auth_root() / "browser-sessions.json"
        self.max_sessions = max_sessions
        self._lock = Lock()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _principal_payload(principal: ClientPrincipal) -> dict[str, Any]:
        permissions = sorted(p for p in BROWSER_SESSION_PERMISSIONS if principal.allows_permission(p))
        return {
            "client_id": f"browser:{principal.client_id}",
            "permissions": permissions,
            "tenants": sorted(principal.tenants),
            "agents": sorted(principal.agents),
            "users": sorted(principal.users),
            "projects": sorted(principal.projects),
            "teams": sorted(principal.teams),
            "organizations": sorted(principal.organizations),
            "default_tenant": principal.default_tenant,
            "default_agent": principal.default_agent,
            "default_user": principal.default_user,
            "default_project": principal.default_project,
            "default_team": principal.default_team,
            "default_organization": principal.default_organization,
        }

    @staticmethod
    def _to_principal(payload: dict[str, Any]) -> ClientPrincipal:
        return ClientPrincipal(
            client_id=str(payload["client_id"]),
            permissions=frozenset(map(str, payload.get("permissions") or [])),
            tenants=frozenset(map(str, payload.get("tenants") or [])),
            agents=frozenset(map(str, payload.get("agents") or [])),
            users=frozenset(map(str, payload.get("users") or [])),
            projects=frozenset(map(str, payload.get("projects") or [])),
            teams=frozenset(map(str, payload.get("teams") or [])),
            organizations=frozenset(map(str, payload.get("organizations") or [])),
            default_tenant=payload.get("default_tenant"),
            default_agent=payload.get("default_agent"),
            default_user=payload.get("default_user"),
            default_project=payload.get("default_project"),
            default_team=payload.get("default_team"),
            default_organization=payload.get("default_organization"),
        )

    def _load(self, now: int) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=503, detail="browser session state is unreadable") from exc
        if int(payload.get("version", 0)) != 1 or not isinstance(payload.get("sessions"), list):
            raise HTTPException(status_code=503, detail="browser session state is invalid")
        active: list[dict[str, Any]] = []
        for row in payload["sessions"]:
            if not isinstance(row, dict):
                raise HTTPException(status_code=503, detail="browser session state is invalid")
            token_hash = str(row.get("token_hash") or "")
            expires_at = _state_int(row.get("expires_at"), "browser session state is invalid")
            principal = row.get("principal")
            if not re.fullmatch(r"[0-9a-f]{64}", token_hash) or not isinstance(principal, dict):
                raise HTTPException(status_code=503, detail="browser session state is invalid")
            if expires_at > now:
                active.append({"token_hash": token_hash, "expires_at": expires_at, "principal": principal})
        return active

    def _write(self, sessions: list[dict[str, Any]]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_path.parent, 0o700)
        except OSError:
            pass
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "sessions": sessions}, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)
        os.chmod(self.state_path, 0o600)

    def issue(self, principal: ClientPrincipal, ttl_seconds: int = 600, *, now: int | None = None) -> dict[str, Any]:
        if ttl_seconds < 60 or ttl_seconds > 900:
            raise HTTPException(status_code=422, detail="browser session ttl must be between 60 and 900 seconds")
        current = int(time.time()) if now is None else int(now)
        token = secrets.token_urlsafe(32)
        row: dict[str, Any] = {
            "token_hash": self._token_hash(token),
            "expires_at": current + ttl_seconds,
            "principal": self._principal_payload(principal),
        }
        if not row["principal"]["permissions"]:
            raise HTTPException(status_code=403, detail="client has no browser-safe permissions")
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        with self._lock, _exclusive_file_lock(lock_path):
            sessions = self._load(current)
            if len(sessions) >= self.max_sessions:
                raise HTTPException(status_code=503, detail="browser session capacity exhausted")
            sessions.append(row)
            self._write(sessions)
        return {"token": token, "expires_at": row["expires_at"], "permissions": list(row["principal"]["permissions"])}

    def authenticate(self, token: str, *, now: int | None = None) -> ClientPrincipal:
        if not token or len(token) > 256:
            raise HTTPException(status_code=401, detail="invalid browser session token")
        current = int(time.time()) if now is None else int(now)
        wanted = self._token_hash(token)
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        with self._lock, _exclusive_file_lock(lock_path):
            sessions = self._load(current)
            match = next((row for row in sessions if hmac.compare_digest(str(row["token_hash"]), wanted)), None)
            self._write(sessions)
        if match is None:
            raise HTTPException(status_code=401, detail="invalid or expired browser session")
        return self._to_principal(dict(match["principal"]))


class ReplayGuard:
    """Reject request replays within the auth window.

    When state_path is configured the nonce digest set is persisted and guarded
    by an OS file lock, so a service restart or sibling process cannot reopen
    the replay window. Raw nonces are never written to disk.
    """

    def __init__(self, max_entries: int = 20000, state_path: Path | None = None) -> None:
        self.max_entries = max_entries
        self.state_path = Path(state_path) if state_path is not None else None
        self._entries: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _digest(client_id: str, nonce: str) -> str:
        return hashlib.sha256((client_id + "\0" + nonce).encode("utf-8")).hexdigest()

    def _read_durable(self, cutoff: int) -> list[dict[str, Any]]:
        if self.state_path is None:
            raise RuntimeError("durable replay state path is required")
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=503, detail="replay protection state is unreadable") from exc
        if int(payload.get("version", 0)) != 1 or not isinstance(payload.get("entries"), list):
            raise HTTPException(status_code=503, detail="replay protection state is invalid")
        clean: list[dict[str, Any]] = []
        for row in payload["entries"]:
            if not isinstance(row, dict):
                raise HTTPException(status_code=503, detail="replay protection state is invalid")
            key = str(row.get("key") or "")
            ts = _state_int(row.get("ts"), "replay protection state is invalid")
            if not re.fullmatch(r"[0-9a-f]{64}", key):
                raise HTTPException(status_code=503, detail="replay protection state is invalid")
            if ts >= cutoff:
                clean.append({"key": key, "ts": ts})
        return clean

    def _write_durable(self, entries: list[dict[str, Any]]) -> None:
        if self.state_path is None:
            raise RuntimeError("durable replay state path is required")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.state_path.parent, 0o700)
        except OSError:
            pass
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "entries": entries}, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)
        os.chmod(self.state_path, 0o600)

    def _accept_in_memory(self, client_id: str, nonce: str, now: int) -> None:
        key = (client_id, nonce)
        cutoff = now - _AUTH_WINDOW_SECONDS
        while self._entries:
            _, ts = next(iter(self._entries.items()))
            if ts >= cutoff:
                break
            self._entries.popitem(last=False)
        if key in self._entries:
            raise HTTPException(status_code=401, detail="replayed request nonce")
        if len(self._entries) >= self.max_entries:
            raise HTTPException(status_code=503, detail="replay protection capacity exhausted")
        self._entries[key] = now

    def accept(self, client_id: str, nonce: str, now: int) -> None:
        with self._lock:
            if self.state_path is None:
                self._accept_in_memory(client_id, nonce, now)
                return
            lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
            with _exclusive_file_lock(lock_path):
                cutoff = now - _AUTH_WINDOW_SECONDS
                entries = self._read_durable(cutoff)
                digest = self._digest(client_id, nonce)
                if any(row["key"] == digest for row in entries):
                    raise HTTPException(status_code=401, detail="replayed request nonce")
                if len(entries) >= self.max_entries:
                    raise HTTPException(status_code=503, detail="replay protection capacity exhausted")
                entries.append({"key": digest, "ts": now})
                self._write_durable(entries)


_registry = ClientRegistry()
_replay = ReplayGuard(state_path=auth_root() / "replay-nonces.json")
_browser_sessions = BrowserSessionRegistry()


def canonical_request(method: str, path_query: str, timestamp: str, nonce: str, body_sha256: str) -> bytes:
    return "\n".join([method.upper(), path_query, timestamp, nonce, body_sha256.lower()]).encode("utf-8")


def required_permission_for_path(path: str, method: str) -> str:
    method = method.upper()
    if path == "/v1/auth/browser-sessions" and method == "POST":
        return "memory:browser-session"
    if path.startswith("/v1/admin/"):
        return "memory:admin"
    if path == "/v1/health/details":
        return "memory:admin"
    if path.startswith("/v1/v5.5/"):
        return "memory:read"
    if path in {"/v1/conversation-ingestion/turn", "/v1/external-sessions/capture"} and method == "POST":
        return "conversation:ingest"
    if path.startswith("/v1/conversation-ingestion/"):
        return "conversation:admin"
    if path.startswith("/v1/sessions") or path.startswith("/v1/session-rotations") or path.startswith("/v1/context-packs/"):
        return "session:manage"
    if path == "/v1/ai-integration/spec":
        return "memory:read"
    if path.startswith("/v1/ai-integration/suggestions"):
        if path.endswith("/promote") and method == "POST":
            return "memory:ai-promote"
        if path.endswith("/decisions") and method == "POST":
            return "memory:ai-review"
        if method in {"GET", "HEAD"}:
            return "memory:ai-review"
        if path == "/v1/ai-integration/suggestions" and method == "POST":
            return "memory:ai-suggest"
        return "memory:admin"
    if path == "/v1/context/retrieve" and method == "POST":
        return "memory:context"
    if path == "/v1/context/retrieve/explain" and method == "POST":
        return "memory:context"
    if path in {"/v1/conversations/recover", "/v1/external-sessions/resolve"}:
        return "memory:context"
    if path.startswith("/v1/checkpoints"):
        return "memory:checkpoint"
    if path.startswith("/v1/derived-artifacts"):
        return "memory:read"
    if path in {"/v1/ontology", "/v1/memory-scopes", "/v1/temporal-spec"}:
        return "memory:read"
    if path == "/v1/input-guard/spec":
        return "memory:read"
    if path == "/v1/operational-memory/spec":
        return "memory:read"
    if path.startswith("/v1/operations/"):
        return "memory:read" if method in {"GET", "HEAD"} else "memory:operational"
    if path == "/v1/economic-memory/spec":
        return "memory:read"
    if path.startswith("/v1/economy/"):
        return "memory:read" if method in {"GET", "HEAD"} else "memory:experience"
    if path == "/v1/decision-record-spec":
        return "memory:read"
    if path.startswith("/v1/decisions"):
        return "memory:read" if method in {"GET", "HEAD"} else "memory:decision"
    if path == "/v1/causal-policy":
        return "memory:read"
    if path.startswith("/v1/knowledge-relations"):
        return "memory:read" if method in {"GET", "HEAD"} else "memory:write"
    if path.startswith("/v1/leases/"):
        return "memory:lease"
    if path.endswith("/validation") and path.startswith("/v1/memories/"):
        return "memory:validate"
    if path.startswith("/v1/experience/"):
        return "memory:experience"
    if path == "/v1/memories/classify":
        return "memory:admin"
    if path == "/v1/ui-governance/spec":
        return "memory:read"
    if path.startswith("/v1/lifecycle"):
        if method in {"GET", "HEAD"}:
            return "memory:read"
        if path == "/v1/lifecycle/m12/close" or path.endswith("/approve") or path.endswith("/purge") or path.endswith("/finalize"):
            return "memory:purge"
        return "memory:lifecycle"
    if path.startswith("/v1/erasure"):
        return "memory:read" if method in {"GET", "HEAD"} else "memory:purge"
    if path == "/v1/purge":
        return "memory:purge"
    if path.startswith("/v1/reports/") or path == "/metrics" or path in {"/v1/dashboard/summary", "/v1/dashboard/human-memory", "/v1/observability/v52"}:
        return "memory:admin"
    if path == "/v1/memories" or path.startswith("/v1/memories/"):
        if method in {"GET", "HEAD"}:
            return "memory:read"
        if method in {"POST", "PUT", "PATCH"}:
            return "memory:write"
    return "memory:admin"


def is_public_path(path: str) -> bool:
    return path in {"/", "/health", "/v1/product-dna", "/v1/product-universality"} or path.startswith("/static/")


async def read_request_body_limited(
    request: Request, *, max_bytes: int = MEMORY_API_REQUEST_MAX_BYTES
) -> bytes:
    """Bound request buffering before HMAC verification to resist memory DoS."""

    if max_bytes <= 0:
        raise HTTPException(status_code=503, detail="invalid request body size policy")
    raw_length = (request.headers.get("Content-Length") or "").strip()
    if raw_length:
        try:
            declared = int(raw_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from exc
        if declared < 0:
            raise HTTPException(status_code=400, detail="invalid Content-Length")
        if declared > max_bytes:
            raise HTTPException(status_code=413, detail="request body exceeds size limit")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="request body exceeds size limit")
        if chunk:
            chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body
    return body


async def authenticate_request(request: Request) -> ClientPrincipal | None:
    if is_public_path(request.url.path):
        return None
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization:
        scheme, sep, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not sep:
            raise HTTPException(status_code=401, detail="invalid authorization scheme")
        principal = _browser_sessions.authenticate(token.strip())
        # Browser bearer sessions are intentionally read-only even when the
        # underlying operator can administrate the service. This prevents a
        # stolen short-lived UI token from reaching mutating admin endpoints
        # such as memory classification. Mutations require signed HMAC auth.
        if not _browser_human_governance_mutation_allowed(request, principal):
            raise HTTPException(status_code=403, detail="browser session mutation is not allowed")
        permission = required_permission_for_path(request.url.path, request.method)
        if not principal.allows_permission(permission):
            raise HTTPException(status_code=403, detail=f"browser session lacks permission: {permission}")
        return principal
    client_id = (request.headers.get("X-Memory-Client-Id") or "").strip()
    timestamp = (request.headers.get("X-Memory-Timestamp") or "").strip()
    nonce = (request.headers.get("X-Memory-Nonce") or "").strip()
    body_sha256 = (request.headers.get("X-Memory-Content-SHA256") or "").strip().lower()
    signature = (request.headers.get("X-Memory-Signature") or "").strip().lower()
    if not client_id or not timestamp or not nonce or not body_sha256 or not signature:
        raise HTTPException(status_code=401, detail="signed Memory API client authentication required")
    if not _NONCE_RE.fullmatch(nonce):
        raise HTTPException(status_code=401, detail="invalid request nonce")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid request timestamp") from exc
    now = int(time.time())
    if abs(now - ts) > _AUTH_WINDOW_SECONDS:
        raise HTTPException(status_code=401, detail="request timestamp outside allowed window")
    body = await read_request_body_limited(request)
    calculated_body = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(calculated_body, body_sha256):
        raise HTTPException(status_code=401, detail="request body hash mismatch")
    principal, secret = _registry.get(client_id)
    path_query = request.url.path + (("?" + request.url.query) if request.url.query else "")
    expected = hmac.new(secret, canonical_request(request.method, path_query, timestamp, nonce, body_sha256), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid request signature")
    permission = required_permission_for_path(request.url.path, request.method)
    if not principal.allows_permission(permission):
        raise HTTPException(status_code=403, detail=f"client lacks permission: {permission}")
    _replay.accept(client_id, nonce, now)
    return principal


def issue_browser_session(principal: ClientPrincipal, ttl_seconds: int = 600) -> dict[str, Any]:
    return _browser_sessions.issue(principal, ttl_seconds)


def principal_from_request(request: Request) -> ClientPrincipal:
    principal = getattr(request.state, "memory_principal", None)
    if not isinstance(principal, ClientPrincipal):
        raise HTTPException(status_code=401, detail="authenticated Memory API client required")
    return principal


def sign_headers(*, client_id: str, secret: bytes, method: str, path_query: str, body: bytes = b"") -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    body_sha256 = hashlib.sha256(body).hexdigest()
    signature = hmac.new(secret, canonical_request(method, path_query, timestamp, nonce, body_sha256), hashlib.sha256).hexdigest()
    return {
        "X-Memory-Client-Id": client_id,
        "X-Memory-Timestamp": timestamp,
        "X-Memory-Nonce": nonce,
        "X-Memory-Content-SHA256": body_sha256,
        "X-Memory-Signature": signature,
    }


# V5.1 M17: short-lived browser sessions may mutate only the human-governance
# namespace. Irreversible lifecycle, erasure and integrity operations remain HMAC-only.
def _browser_human_governance_mutation_allowed(request: Request, principal: ClientPrincipal) -> bool:
    method = request.method.upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return True
    if not principal.allows_permission("memory:admin"):
        return False
    host = (request.headers.get("host") or "").split(":", 1)[0].strip("[]").lower()
    if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return False
    origin = (request.headers.get("origin") or "").strip().lower()
    if origin and not (
        origin.startswith("http://127.0.0.1:")
        or origin.startswith("http://localhost:")
        or origin.startswith("http://[::1]:")
        or origin == "http://testserver"
    ):
        return False
    path = request.url.path
    if method == "PATCH" and path.startswith("/v1/admin/memories/") and path.endswith("/display-metadata"):
        return True
    if method != "POST":
        return False
    if path == "/v1/admin/memories/delete-batch":
        return True
    if not path.startswith("/v1/admin/memories/"):
        return False
    return any(path.endswith(suffix) for suffix in (
        "/protect", "/archive", "/delete", "/undo-delete", "/promote-scope"
    ))
