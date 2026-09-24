from __future__ import annotations

import hashlib
import json
from pathlib import Path

from memory_permanent.integrity_anchor import IntegrityAnchorManager


def _loader(path:Path)->bytes:return hashlib.sha256(path.name.encode()).digest()

def test_anchor_tamper_rotation_chain_and_degraded_destination(tmp_path:Path)->None:
    anchors=tmp_path/"external"/"anchors";keys=tmp_path/"external"/"keys";m=IntegrityAnchorManager(anchor_root=anchors,key_root=keys,key_loader=_loader)
    first=m.create_anchor(root_hash="a"*64,scope_type="SYSTEM",scope_id="memory");p=Path(first["external_anchor_ref"]);assert m.verify_manifest(p)["valid"]
    rotation=m.rotate_key();assert rotation["old_key_version"]==1 and rotation["new_key_version"]==2;assert rotation["old_public_key_sha256"]!=rotation["new_public_key_sha256"]
    second=m.create_anchor(root_hash="b"*64,scope_type="SYSTEM",scope_id="memory");assert second["signature_key_version"]==2;assert second["previous_manifest_hash"]==first["manifest_hash"]
    chain=m.verify_chain();assert chain["ok"] and chain["count"]==2;assert m.verify_manifest(p)["valid"]
    tampered=json.loads(p.read_text(encoding="utf-8"));tampered["root_hash"]="c"*64;p.write_text(json.dumps(tampered),encoding="utf-8");assert not m.verify_manifest(p)["valid"]
    blocked=tmp_path/"not-a-directory";blocked.write_text("occupied",encoding="utf-8");d=IntegrityAnchorManager(anchor_root=blocked,key_root=keys,key_loader=_loader).try_anchor(root_hash="d"*64,scope_type="SYSTEM",scope_id="memory")
    assert d["state"]=="DEGRADED" and not d["anchored"] and not d["canonical_write_blocked"]
