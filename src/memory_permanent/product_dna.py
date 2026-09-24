"""Product DNA identity presented by MEMORIA-PERMANENTE V4."""

from __future__ import annotations

import hashlib
import json
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any


def product_dna_path() -> Path:
    source_path = Path(__file__).resolve().parents[2] / ".wmcp" / "product-dna.json"
    if source_path.is_file():
        return source_path
    target_path = Path(__file__).resolve().parents[1] / "share" / "memoria-permanente" / ".wmcp" / "product-dna.json"
    if target_path.is_file():
        return target_path
    installed_path = Path(sysconfig.get_path("data")) / "share" / "memoria-permanente" / ".wmcp" / "product-dna.json"
    if installed_path.is_file():
        return installed_path
    raise FileNotFoundError("MEMORIA-PERMANENTE product DNA is not installed")


@lru_cache(maxsize=1)
def get_product_dna() -> tuple[dict[str, Any], str]:
    manifest_path = product_dna_path()
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8-sig"))
    fingerprint = hashlib.sha256(raw).hexdigest()
    return manifest, fingerprint


def response_headers() -> dict[str, str]:
    manifest, fingerprint = get_product_dna()
    return {
        "X-Memory-Product-ID": str(manifest["product_id"]),
        "X-Memory-Product-DNA": fingerprint,
        "X-Memory-Canonical-Identity": str(manifest["canonical_identity"]),
        "X-WMCP-Product-ID": str(manifest["product_id"]),
        "X-WMCP-Product-DNA": fingerprint,
        "X-WMCP-Manufacturer": str(manifest["manufacturer"]),
        "X-WMCP-Canonical-Identity": str(manifest["canonical_identity"]),
        "X-WMCP-Origin-Domain": str(manifest["origin_domain"]),
        "X-WMCP-Identity-SHA256": str(manifest["identity_sha256"]),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        "Cache-Control": "no-store",
    }


def public_identity() -> dict[str, Any]:
    manifest, fingerprint = get_product_dna()
    return {
        "schema": manifest.get("schema"),
        "product_id": manifest.get("product_id"),
        "product_name": manifest.get("product_name"),
        "manufacturer": manifest.get("manufacturer"),
        "manufacturer_project_id": manifest.get("manufacturer_project_id"),
        "canonical_identity": manifest.get("canonical_identity"),
        "origin_urn": manifest.get("origin_urn"),
        "origin_domain": manifest.get("origin_domain"),
        "identity_sha256": manifest.get("identity_sha256"),
        "trust_class": manifest.get("trust_class"),
        "dna_version": manifest.get("dna_version"),
        "dna_sha256": fingerprint,
        "capabilities": list(manifest.get("capabilities") or []),
    }
