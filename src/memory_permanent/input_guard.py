from __future__ import annotations

import base64
import binascii
import html
import re
import unicodedata
import urllib.parse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

INPUT_GUARD_VERSION = "IG-2.0.0"
_MAX_TEXT_CHARS = 200_000
_MAX_DECODE_DEPTH = 3

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")
_BASE64_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/_-])([A-Za-z0-9+/_-]{20,8192}={0,2})(?![A-Za-z0-9+/_-])")
_HEX_TOKEN_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{24,8192})(?![0-9A-Fa-f])")
_OBFUSCATED_TOKEN_RE = re.compile(r"(?:\b[a-z0-9]\W+){3,}[a-z0-9]\b", re.IGNORECASE)

_CONFUSABLES = str.maketrans({
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a", "5": "s", "6": "g", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s", "!": "i", "|": "i",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i",
    "Α": "a", "Β": "b", "Ε": "e", "Ι": "i", "Κ": "k", "Μ": "m", "Ν": "n", "Ο": "o", "Ρ": "p", "Τ": "t", "Χ": "x",
})

_OVERRIDE_ACTIONS = (
    "ignore", "disregard", "forget", "override", "replace", "supersede", "cancel", "omit",
    "desconsidere", "ignore", "esqueca", "substitua", "anule", "omita",
    "ignora", "omite", "olvida", "reemplaza",
    "ignora", "dimentica", "sostituisci",
    "ignore", "ignorez", "oublie", "remplace",
    "ignoriere", "vergiss", "ersetze",
)
_PREVIOUS_MARKERS = (
    "previous", "prior", "earlier", "above",
    "anterior", "anteriores", "previo", "previas", "previas", "precedente", "precedentes", "precedenti",
    "vorherige", "vorherigen", "vorherigeanweisungen",
)
_CONTROL_TARGETS = (
    "instruction", "instructions", "directive", "directives", "prompt", "systemprompt", "system", "developer",
    "policy", "policies", "guardrail", "guardrails", "rule", "rules", "control", "controls",
    "instrucao", "instrucoes", "diretriz", "diretrizes", "sistema", "politica", "politicas", "regra", "regras", "controle", "controles",
    "instruccion", "instrucciones", "directiva", "directivas", "sistema", "norma", "normas", "regla", "reglas",
    "istruzione", "istruzioni", "direttiva", "direttive", "sistema", "regola", "regole",
    "instruction", "instructions", "directive", "directives", "systeme", "regle", "regles",
    "anweisung", "anweisungen", "system", "regel", "regeln",
)
_SECURITY_ACTIONS = (
    "disable", "bypass", "circumvent", "evade", "remove", "turnoff", "break",
    "desative", "desabilite", "contorne", "burle", "evite",
    "desactiva", "deshabilita", "elude", "omite", "evita",
    "disabilita", "aggira", "eludi",
    "desactive", "contourne", "evite",
    "deaktiviere", "umgehe", "umgeh",
)
_SECURITY_TARGETS = (
    "security", "authentication", "authorization", "accesscontrol", "rls", "audit", "logging", "governor", "sandbox",
    "seguranca", "autenticacao", "autorizacao", "controledeacesso", "auditoria",
    "seguridad", "autenticacion", "autorizacion", "controldeacceso",
    "sicurezza", "autenticazione", "autorizzazione",
    "securite", "authentification", "autorisation",
    "sicherheit", "authentifizierung", "autorisierung",
)
_DISCLOSURE_ACTIONS = (
    "reveal", "show", "display", "print", "export", "send", "exfiltrate", "dump", "leak", "return",
    "revele", "mostre", "exiba", "imprima", "exporte", "envie", "vaze",
    "revela", "muestra", "muestra", "imprime", "exporta", "envia",
    "rivela", "mostra", "visualizza", "stampa", "esporta", "invia",
    "revele", "revelez", "montre", "montrez", "affiche", "affichez", "imprime", "exporte", "envoyez",
    "zeige", "enthulle", "drucke", "exportiere", "sende",
)
_SECRET_TARGETS = (
    "secret", "secrets", "credential", "credentials", "password", "passwords", "token", "tokens", "cookie", "cookies",
    "apikey", "privatekey", "systemprompt",
    "senha", "senhas", "segredo", "segredos", "credencial", "credenciais", "chaveprivada",
    "contrasena", "contrasenas", "secreto", "secretos", "credencial", "credenciales",
    "segreto", "segreti", "credenziale", "credenziali",
    "secret", "motdepasse", "identifiant",
    "geheimnis", "passwort", "anmeldedaten",
)
_EXEC_ACTIONS = (
    "execute", "run", "launch", "invoke", "eval", "exec", "decodeandrun",
    "execute", "rode", "inicie", "avalie", "decodifique",
    "ejecuta", "ejecute", "lancia", "esegui", "executez", "lancez", "fuhre", "fuehre",
)
_TOOL_TARGETS = (
    "powershell", "cmdexe", "commandprompt", "shell", "bash", "terminal", "python", "javascript", "toolcall", "functioncall",
)
_PRIVILEGE_TARGETS = (
    "root", "administrator", "admin", "superuser", "systemuser", "localsystem", "administrador", "administrateur", "amministratore",
)
_NEGATIONS = (
    "never", "do not", "dont", "don't", "must not", "should not", "no ", "not ",
    "nao", "nunca", "jamais", "no ", "nunca", "non ", "ne ", "pas ", "nicht", "niemals",
)
_STRUCTURED_UNTRUSTED_REASONS = {
    "ATTACHMENT": "UNTRUSTED_ATTACHMENT",
    "TOOL_OUTPUT": "UNTRUSTED_TOOL_OUTPUT",
    "EXTERNAL_DOCUMENT": "UNTRUSTED_EXTERNAL_DOCUMENT",
    "WEB_CONTENT": "UNTRUSTED_WEB_CONTENT",
}


@dataclass(frozen=True, slots=True)
class GuardDecision:
    decision: str
    reason: str
    risk_score: int


@dataclass(frozen=True, slots=True)
class GuardBatchDecision:
    decisions: tuple[GuardDecision, ...]
    distributed_attack: bool
    reason: str

    def __iter__(self) -> Iterator[GuardDecision]:
        return iter(self.decisions)

    def __len__(self) -> int:
        return len(self.decisions)

    def __getitem__(self, index: int) -> GuardDecision:
        return self.decisions[index]


class InputGuard:
    """Second-generation deterministic firewall for model context.

    The guard is intentionally model-independent. It preserves raw memory but
    prevents adversarial content from entering composed model context. Trust is
    accepted only from authenticated provenance supplied by the caller.
    """

    version = INPUT_GUARD_VERSION

    @staticmethod
    def _strip_accents(value: str) -> str:
        return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))

    @classmethod
    def _normalize(cls, content: str) -> str:
        value = unicodedata.normalize("NFKC", str(content or ""))
        value = _ZERO_WIDTH_RE.sub("", value)
        value = value.translate(_CONFUSABLES)
        value = cls._strip_accents(value).casefold()
        value = re.sub(r"[\t\r\n]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value)

    @classmethod
    def _flatten(cls, value: Any, *, depth: int = 0) -> str:
        if depth > 10 or value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, dict):
            parts: list[str] = []
            for key, item in value.items():
                parts.append(str(key))
                parts.append(cls._flatten(item, depth=depth + 1))
            return " ".join(part for part in parts if part)
        if isinstance(value, (list, tuple, set, frozenset)):
            return " ".join(cls._flatten(item, depth=depth + 1) for item in value)
        return str(value)

    @staticmethod
    def _printable_ratio(value: str) -> float:
        if not value:
            return 0.0
        return sum(1 for ch in value if ch.isprintable() or ch.isspace()) / len(value)

    @staticmethod
    def _decode_unicode_escapes(value: str) -> str:
        def repl(match: re.Match[str]) -> str:
            token = match.group(1) or match.group(2)
            try:
                return chr(int(token, 16))
            except ValueError:
                return match.group(0)
        return _UNICODE_ESCAPE_RE.sub(repl, value)

    @classmethod
    def _decode_once(cls, raw: str) -> list[tuple[str, str]]:
        variants: list[tuple[str, str]] = []
        entity = html.unescape(raw)
        if entity != raw:
            variants.append(("HTML_ENTITY", entity))
        percent = urllib.parse.unquote(raw)
        if percent != raw:
            variants.append(("PERCENT", percent))
        escaped = cls._decode_unicode_escapes(raw)
        if escaped != raw:
            variants.append(("UNICODE_ESCAPE", escaped))

        for match in _BASE64_TOKEN_RE.finditer(raw):
            token = match.group(1)
            padded = token + "=" * ((4 - len(token) % 4) % 4)
            attempts = (("BASE64", False), ("URLSAFE_BASE64", True))
            for name, urlsafe in attempts:
                try:
                    decoded = base64.urlsafe_b64decode(padded.encode("ascii")) if urlsafe else base64.b64decode(padded.encode("ascii"), validate=False)
                    text = decoded.decode("utf-8", errors="strict")
                except (ValueError, UnicodeDecodeError, binascii.Error):
                    continue
                if len(text) >= 6 and cls._printable_ratio(text) >= 0.85:
                    variants.append((name, text))
                    break

        for match in _HEX_TOKEN_RE.finditer(raw):
            token = match.group(1)
            if len(token) % 2:
                continue
            try:
                text = bytes.fromhex(token).decode("utf-8", errors="strict")
            except (ValueError, UnicodeDecodeError):
                continue
            if len(text) >= 6 and cls._printable_ratio(text) >= 0.85:
                variants.append(("HEX", text))
        return variants

    @classmethod
    def _decoded_variants(cls, raw: str) -> list[tuple[str, str]]:
        queue: list[tuple[str, str, int]] = [("RAW", raw, 0)]
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        while queue and len(result) < 64:
            kind, value, depth = queue.pop(0)
            normalized = cls._normalize(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append((kind, normalized))
            if depth >= _MAX_DECODE_DEPTH:
                continue
            for child_kind, child in cls._decode_once(value):
                queue.append((child_kind, child, depth + 1))
        return result

    @staticmethod
    def _contains_any(text: str, compact: str, words: Iterable[str]) -> bool:
        for word in words:
            token = str(word).casefold()
            if token in text or token.replace(" ", "") in compact:
                return True
        return False

    @classmethod
    def _negated(cls, text: str, action_words: Iterable[str]) -> bool:
        for action in action_words:
            token = cls._normalize(action)
            pos = text.find(token)
            if pos < 0:
                continue
            prefix = text[max(0, pos - 24):pos]
            if any(neg.strip() in prefix or prefix.endswith(neg) for neg in _NEGATIONS):
                return True
        return False

    @classmethod
    def _semantic_signals(cls, text: str) -> list[tuple[str, int]]:
        compact = cls._compact(text)
        signals: list[tuple[str, int]] = []

        override = cls._contains_any(text, compact, _OVERRIDE_ACTIONS)
        control = cls._contains_any(text, compact, _CONTROL_TARGETS)
        previous = cls._contains_any(text, compact, _PREVIOUS_MARKERS)
        if override and control and not cls._negated(text, _OVERRIDE_ACTIONS):
            signals.append(("OVERRIDE_CONTROL", 50 if previous else 40))

        security_action = cls._contains_any(text, compact, _SECURITY_ACTIONS)
        security_target = cls._contains_any(text, compact, _SECURITY_TARGETS)
        if security_action and security_target and not cls._negated(text, _SECURITY_ACTIONS):
            signals.append(("DISABLE_SECURITY", 55))

        disclosure = cls._contains_any(text, compact, _DISCLOSURE_ACTIONS)
        secret = cls._contains_any(text, compact, _SECRET_TARGETS)
        if disclosure and secret and not cls._negated(text, _DISCLOSURE_ACTIONS):
            signals.append(("EXFILTRATE_SECRET", 55))

        execute = cls._contains_any(text, compact, _EXEC_ACTIONS)
        tool = cls._contains_any(text, compact, _TOOL_TARGETS)
        if execute and tool and not cls._negated(text, _EXEC_ACTIONS):
            signals.append(("EXECUTE_TOOL_DIRECTIVE", 45))

        privilege = cls._contains_any(text, compact, _PRIVILEGE_TARGETS)
        impersonation = any(token in compact for token in ("actas", "become", "switchto", "ajacomo", "tornese", "assume", "impersonate"))
        if privilege and (execute or override or impersonation):
            signals.append(("PRIVILEGE_ESCALATION", 50))

        compact_signatures = (
            ("OVERRIDE_CONTROL", (
                "ignorepreviousinstructions", "ignoreallpreviousinstructions", "disregardpriordirectives",
                "desconsidereasinstrucoesanteriores", "desconsidereasregrasanteriores",
                "ignoralasinstruccionesanteriores", "omitelasnormasanteriores",
                "ignoraleregoleprecedenti", "ignorelesreglesprecedentes", "ignorierevorherigeregeln",
            ), 55),
            ("DISABLE_SECURITY", (
                "disablesecurity", "bypassauthentication", "desativeseguranca", "contorneautenticacao",
                "desactivaseguridad", "aggiraautenticazione", "contourneauthentification", "umgeheauthentifizierung",
            ), 55),
            ("EXFILTRATE_SECRET", (
                "revealsecret", "revealtoken", "showpassword", "displaysecrettoken", "exportsecrettoken",
                "mostreasenha", "mostreotoken", "muestralacredencialsecreta", "mostrailsegreto",
                "affichelemotdepasse", "zeigedaspasswort",
            ), 55),
        )
        for name, needles, weight in compact_signatures:
            if any(needle in compact for needle in needles):
                # Respect explicit negation even for compact signatures.
                if name == "EXFILTRATE_SECRET" and cls._negated(text, _DISCLOSURE_ACTIONS):
                    continue
                if name == "DISABLE_SECURITY" and cls._negated(text, _SECURITY_ACTIONS):
                    continue
                signals.append((name, weight))

        if re.search(r"\b(mark|treat|consider|set|declare|classify|marque|trate|considere|defina|declare)\b.{0,80}\b(trusted|validated|authoritative|governor.?eligible|confiavel|validado|autoritativo)\b", text):
            signals.append(("SELF_ATTEST_TRUST", 45))
        names = {name for name, _ in signals}
        if "OVERRIDE_CONTROL" in names:
            signals.append(("CONTROL_OVERRIDE", 0))
        if "DISABLE_SECURITY" in names:
            signals.append(("SECURITY_BYPASS", 0))
        return signals

    @classmethod
    def _is_obfuscated(cls, raw: str, normalized: str) -> bool:
        if _OBFUSCATED_TOKEN_RE.search(raw):
            return True
        if re.search(r"\b[a-z]*[01345789][a-z0-9]*\b", raw.casefold()):
            return True
        if _ZERO_WIDTH_RE.search(raw):
            return True
        raw_compact = re.sub(r"[^a-z0-9]+", "", cls._strip_accents(unicodedata.normalize("NFKC", raw)).casefold())
        return bool(raw_compact and raw_compact != cls._compact(normalized) and any(ch.isdigit() for ch in raw))

    @classmethod
    def _content_score(cls, raw: str) -> tuple[int, list[str]]:
        best = 0
        reasons: list[str] = []
        base_normalized = cls._normalize(raw)
        obfuscated = cls._is_obfuscated(raw, base_normalized)
        for kind, normalized in cls._decoded_variants(raw):
            signals = cls._semantic_signals(normalized)
            if not signals:
                continue
            score = min(100, sum(weight for _, weight in signals))
            best = max(best, score)
            reasons.extend(name for name, _ in signals)
            if kind != "RAW":
                reasons.extend(["ENCODED_INSTRUCTION_PAYLOAD", f"ENCODED_PAYLOAD:{kind}"])
                if kind == "PERCENT":
                    reasons.append("ENCODED_PAYLOAD:URL_PERCENT")
                best = max(best, min(100, score + 15))
            if obfuscated:
                reasons.append("OBFUSCATED_INSTRUCTION")
                best = max(best, min(100, score + 10))
        return best, list(dict.fromkeys(reasons))

    @staticmethod
    def _decision(score: int, reasons: list[str], provenance: str) -> GuardDecision:
        score = min(max(int(score), 0), 100)
        unique = list(dict.fromkeys(reason for reason in reasons if reason))
        if score >= 50:
            return GuardDecision("QUARANTINE", ";".join(unique), score)
        if score >= 25:
            return GuardDecision("UNTRUSTED_CONTEXT", ";".join(unique), score)
        return GuardDecision("ALLOW", ";".join(unique) if unique else (provenance or "trusted"), score)

    def assess(
        self,
        content: Any,
        *,
        provenance: str,
        trusted: bool,
        conflicts: bool = False,
        source_kind: str = "MEMORY",
    ) -> GuardDecision:
        raw = self._flatten(content)
        if len(raw) > _MAX_TEXT_CHARS:
            raw = raw[:_MAX_TEXT_CHARS]
            truncated = True
        else:
            truncated = False
        score, reasons = self._content_score(raw)
        kind = str(source_kind or "MEMORY").strip().upper()
        if not trusted:
            score += 20
            reasons.append("UNTRUSTED_PROVENANCE")
            structured_reason = _STRUCTURED_UNTRUSTED_REASONS.get(kind)
            if structured_reason:
                score += 10
                reasons.append(structured_reason)
        if conflicts:
            score += 30
            reasons.append("CONFLICTING_MEMORY")
        if truncated:
            score += 20
            reasons.append("OVERSIZED_INPUT")
        return self._decision(score, reasons, provenance)

    @staticmethod
    def _infer_source_kind(record: dict[str, Any]) -> str:
        explicit = str(record.get("source_kind") or "").strip().upper()
        if explicit:
            return explicit
        tags = {str(tag).strip().upper() for tag in (record.get("tags") or [])}
        for candidate in ("TOOL_OUTPUT", "ATTACHMENT", "EXTERNAL_DOCUMENT", "WEB_CONTENT"):
            if candidate in tags:
                return candidate
        source = str(record.get("source") or "").upper()
        if "TOOL" in source:
            return "TOOL_OUTPUT"
        if "ATTACH" in source or "UPLOAD" in source:
            return "ATTACHMENT"
        if "WEB" in source:
            return "WEB_CONTENT"
        if "EXTERNAL" in source or "DOCUMENT" in source:
            return "EXTERNAL_DOCUMENT"
        return "MEMORY"

    def assess_record(self, record: dict[str, Any], *, trusted: bool, conflicts: bool = False) -> GuardDecision:
        payload = {
            "content_text": record.get("content_text"),
            "content": record.get("content") if "content" in record else record.get("content_json"),
            "tool_output": record.get("tool_output"),
            "attachment": record.get("attachment"),
            "artifact": record.get("artifact"),
            "metadata": record.get("metadata"),
        }
        return self.assess(
            payload,
            provenance=str(record.get("source") or record.get("provenance") or "unknown"),
            trusted=trusted,
            conflicts=conflicts,
            source_kind=self._infer_source_kind(record),
        )

    def assess_batch(
        self,
        records: list[dict[str, Any]],
        *,
        trusted_flags: list[bool] | None = None,
        conflict_flags: list[bool] | None = None,
    ) -> GuardBatchDecision:
        if trusted_flags is None:
            trusted_flags = [bool(record.get("trusted", False)) for record in records]
        if len(records) != len(trusted_flags):
            raise ValueError("records and trusted_flags length mismatch")
        if conflict_flags is None:
            conflict_flags = [bool(record.get("conflicts", False)) for record in records]
        if len(records) != len(conflict_flags):
            raise ValueError("records and conflict_flags length mismatch")

        normalized_records: list[dict[str, Any]] = []
        for record in records:
            if "content_text" in record or "content_json" in record:
                normalized_records.append(record)
            else:
                normalized_records.append({
                    "source": record.get("provenance") or "batch",
                    "source_kind": record.get("source_kind") or "MEMORY",
                    "content_text": record.get("content"),
                    "content_json": record.get("structured") or {},
                    "tags": record.get("tags") or [],
                })

        decisions = [
            self.assess_record(record, trusted=trusted_flags[i], conflicts=conflict_flags[i])
            for i, record in enumerate(normalized_records)
        ]
        raw_parts = [self._flatten({"content_text": r.get("content_text"), "content_json": r.get("content_json")}) for r in normalized_records]
        distributed = False
        for width in (2, 3, 4):
            for start in range(max(0, len(records) - width + 1)):
                end = start + width
                window = raw_parts[start:end]
                if not all(part.strip() for part in window):
                    continue
                combined_score, combined_reasons = self._content_score(" ".join(window))
                individual_max = max((self._content_score(part)[0] for part in window), default=0)
                if combined_score < 50 or individual_max >= 50:
                    continue
                distributed = True
                for idx in range(start, end):
                    if trusted_flags[idx]:
                        continue
                    previous = decisions[idx]
                    reasons = [reason for reason in previous.reason.split(";") if reason]
                    reasons.extend(["DISTRIBUTED_ATTACK", *combined_reasons])
                    decisions[idx] = self._decision(max(50, previous.risk_score, combined_score), reasons, str(normalized_records[idx].get("source") or "batch"))
        return GuardBatchDecision(
            decisions=tuple(decisions),
            distributed_attack=distributed,
            reason="DISTRIBUTED_ATTACK" if distributed else "ITEM_LEVEL_ONLY",
        )


def input_guard_spec() -> dict[str, object]:
    return {
        "version": INPUT_GUARD_VERSION,
        "decisions": ["ALLOW", "UNTRUSTED_CONTEXT", "QUARANTINE"],
        "languages": ["en", "pt", "es", "it", "fr", "de"],
        "normalization": ["NFKC", "CASEFOLD", "ZERO_WIDTH", "CONFUSABLES", "DIACRITICS", "LEETSPEAK", "SPACED_LETTERS"],
        "encodings": ["PERCENT", "HTML_ENTITY", "UNICODE_ESCAPE", "BASE64", "URLSAFE_BASE64", "HEX"],
        "structured_sources": ["MEMORY", "ATTACHMENT", "TOOL_OUTPUT", "EXTERNAL_DOCUMENT", "WEB_CONTENT"],
        "distributed_detection": True,
        "bounded_decode_depth": _MAX_DECODE_DEPTH,
        "max_text_chars": _MAX_TEXT_CHARS,
    }
