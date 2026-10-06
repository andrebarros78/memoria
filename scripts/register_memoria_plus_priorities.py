from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
sys.path.insert(0, str(ROOT / "src"))
from memory_permanent.signed_client import SignedMemoryClient  # noqa: E402

DOC = ROOT / "docs" / "MEMORIA_PLUS_PRIORIDADES_CORRECAO.md"
EVIDENCE = ROOT / "evidence" / "MEMORIA_PLUS_REGISTRATION_PROOF.json"
TEXT = DOC.read_text(encoding="utf-8")
DOC_SHA = hashlib.sha256(DOC.read_bytes()).hexdigest()

pattern = re.compile(
    r"###\s+(\d{2})\.\s+(.+?)\n\*\*Problema:\*\*\s*(.+?)\s{2}\n"
    r"\*\*Bloco de correção:\*\*\s*(.+?)\s{2}\n"
    r"\*\*Aceitação:\*\*\s*(.+?)(?=\n\n###|\n\n##|\Z)",
    re.S,
)
rows = []
for m in pattern.finditer(TEXT):
    rank = int(m.group(1))
    rows.append({
        "rank": rank,
        "priority": "P0" if rank <= 6 else ("P1" if rank <= 12 else "P2"),
        "title": m.group(2).strip(),
        "problem": re.sub(r"\s+", " ", m.group(3)).strip(),
        "correction_block": re.sub(r"\s+", " ", m.group(4)).strip(),
        "acceptance": re.sub(r"\s+", " ", m.group(5)).strip(),
    })
if len(rows) != 18:
    raise RuntimeError(f"expected 18 priorities, parsed {len(rows)}")

client = SignedMemoryClient("http://127.0.0.1:8787", "local-admin")
created = []
for row in rows:
    rank = row["rank"]
    key = f"memoria-plus.priority.{rank:02d}"
    payload = {
        "namespace": "MEMORIA_PLUS",
        "memory_key": key,
        "category": "CONSTRAINT",
        "content": {
            **row,
            "status": "OPEN",
            "tag_canonical": "MEMORIA PLUS",
            "source_document": str(DOC),
            "source_document_sha256": DOC_SHA,
            "execution_order": rank,
        },
        "content_text": (
            f"MEMORIA PLUS prioridade {rank:02d} {row['priority']}: {row['title']}. "
            f"Problema: {row['problem']} Correção: {row['correction_block']} "
            f"Aceitação: {row['acceptance']}"
        ),
        "provenance": {
            "registration": "user-requested-project-priority",
            "source_document_sha256": DOC_SHA,
            "tag": "MEMORIA PLUS",
        },
        "confidence": 1.0,
        "source": "project-governance",
        "source_version": "MEMORIA_PLUS_V1",
        "tags": ["MEMORIA PLUS", "V4", "CORRECAO", row["priority"], f"PRIORIDADE_{rank:02d}"],
        "changed_by": "local-admin",
        "sharing_scope": "SYSTEM_SHARED",
        "validation_status": "UNVALIDATED",
        "governor_eligible": False,
    }
    status, body = client.request(
        "POST", "/v1/memories", payload,
        extra_headers={"Idempotency-Key": f"memoria-plus-v1-priority-{rank:02d}"},
    )
    if status != 201:
        raise RuntimeError({"rank": rank, "status": status, "body": body})
    item_id = body["item_id"]
    v_status, versions = client.request("GET", f"/v1/memories/{item_id}/versions")
    if v_status != 200 or not versions.get("versions"):
        raise RuntimeError({"rank": rank, "verification_status": v_status, "body": versions})
    created.append({
        "rank": rank,
        "priority": row["priority"],
        "memory_key": key,
        "item_id": item_id,
        "version_count": len(versions["versions"]),
        "latest_version": versions["versions"][-1]["version_no"],
        "latest_content_sha256": versions["versions"][-1]["content_sha256"],
    })

manifest_payload = {
    "namespace": "MEMORIA_PLUS",
    "memory_key": "memoria-plus.manifest.v1",
    "category": "CONSTRAINT",
    "content": {
        "title": "MEMORIA PLUS — Manifesto de Prioridades de Correção",
        "tag_canonical": "MEMORIA PLUS",
        "total_priorities": 18,
        "priority_blocks": {"P0": [1,2,3,4,5,6], "P1": [7,8,9,10,11,12], "P2": [13,14,15,16,17,18]},
        "execution_order": list(range(1,19)),
        "memory_item_ids": [x["item_id"] for x in created],
        "source_document": str(DOC),
        "source_document_sha256": DOC_SHA,
        "closure_rule": "P0 01-06 before V4_FULL_PROVEN or functional expansion",
    },
    "content_text": "MEMORIA PLUS manifesto mestre: 18 prioridades ordenadas P0 01-06, P1 07-12, P2 13-18. Executar em ordem canônica 01 até 18.",
    "provenance": {"registration": "user-requested-project-priority", "source_document_sha256": DOC_SHA, "tag": "MEMORIA PLUS"},
    "confidence": 1.0,
    "source": "project-governance",
    "source_version": "MEMORIA_PLUS_V1",
    "tags": ["MEMORIA PLUS", "V4", "MANIFESTO", "CORRECAO"],
    "changed_by": "local-admin",
    "sharing_scope": "SYSTEM_SHARED",
    "validation_status": "UNVALIDATED",
    "governor_eligible": False,
}
manifest_status, manifest_body = client.request(
    "POST", "/v1/memories", manifest_payload,
    extra_headers={"Idempotency-Key": "memoria-plus-v1-manifest"},
)
if manifest_status != 201:
    raise RuntimeError({"manifest_status": manifest_status, "body": manifest_body})

proof = {
    "generated_at": datetime.now(UTC).isoformat(),
    "tag": "MEMORIA PLUS",
    "document": str(DOC),
    "document_sha256": DOC_SHA,
    "priorities_registered": len(created),
    "manifest_item_id": manifest_body["item_id"],
    "items": created,
    "all_unvalidated_by_design": True,
    "governor_eligible": False,
    "registration": "PASS" if len(created) == 18 else "FAIL",
}
EVIDENCE.write_text(json.dumps(proof, indent=2), encoding="utf-8")
print(json.dumps({
    "registration": proof["registration"],
    "tag": proof["tag"],
    "priorities_registered": proof["priorities_registered"],
    "manifest_item_id": proof["manifest_item_id"],
    "document_sha256": DOC_SHA,
    "first_item": created[0]["item_id"],
    "last_item": created[-1]["item_id"],
}, indent=2))
