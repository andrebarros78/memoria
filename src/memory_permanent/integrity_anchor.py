from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .secret_sanitizer import (
    default_vault_root,
    platform_key_provider,
    platform_protected_key_path,
)

CONTRACT="MEMORIA_PERMANENTE_INTEGRITY_ANCHOR_V1"
SCHEMA="memoria-permanente.integrity-anchor.v1"

def _canon(v:Any)->bytes:
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
def _sha(v:bytes)->str:return hashlib.sha256(v).hexdigest()
def _write(path:Path,payload:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f:
            json.dump(payload,f,ensure_ascii=False,sort_keys=True,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass

class IntegrityAnchorManager:
    def __init__(self,*,anchor_root:str|Path,key_root:str|Path|None=None,key_loader:Callable[[Path],bytes]|None=None)->None:
        self.anchor_root=Path(anchor_root)
        self.key_root=Path(key_root) if key_root else default_vault_root()/"integrity-anchor"
        self.key_loader=key_loader or self._platform_key
        self.current=self.key_root/"current-version.txt"
    @staticmethod
    def _platform_key(path:Path)->bytes:
        return platform_key_provider(path,machine_scope=True,entropy=b"MEMORIA-PERMANENTE:INTEGRITY-ANCHOR:V1").load_or_create()
    def _key_path(self,v:int)->Path:
        return platform_protected_key_path(self.key_root,f"integrity-anchor-v{v:04d}")
    def _version(self)->int:
        try:return max(1,int(self.current.read_text(encoding="ascii").strip()))
        except (FileNotFoundError,ValueError,OSError):return 1
    def _set_version(self,v:int)->None:
        self.key_root.mkdir(parents=True,exist_ok=True);self.current.write_text(str(v)+"\n",encoding="ascii")
    def _private(self,v:int)->Ed25519PrivateKey:
        raw=bytes(self.key_loader(self._key_path(v)))
        if len(raw)!=32:raise RuntimeError("integrity anchor key must be 32 bytes")
        return Ed25519PrivateKey.from_private_bytes(raw)
    @staticmethod
    def _pub(k:Ed25519PrivateKey)->bytes:
        return k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    def rotate_key(self)->dict[str,Any]:
        old=self._version();oldk=self._private(old);new=old+1;newk=self._private(new);self._set_version(new)
        return {"contract":CONTRACT,"old_key_version":old,"new_key_version":new,"old_public_key_sha256":_sha(self._pub(oldk)),"new_public_key_sha256":_sha(self._pub(newk))}
    def _latest(self)->Path|None:
        paths=sorted(self.anchor_root.glob("anchor-*.json")) if self.anchor_root.is_dir() else []
        return paths[-1] if paths else None
    def create_anchor(self,*,root_hash:str,scope_type:str,scope_id:str,range_start:str|int|None=None,range_end:str|int|None=None,metadata:dict[str,Any]|None=None)->dict[str,Any]:
        root=str(root_hash).strip().lower()
        if len(root)!=64 or any(c not in "0123456789abcdef" for c in root):raise ValueError("root_hash must be SHA-256 hex")
        ver=self._version();priv=self._private(ver);pub=self._pub(priv);prev=self._latest();prev_hash=None
        if prev:
            prev_hash=str(json.loads(prev.read_text(encoding="utf-8-sig")).get("manifest_hash") or "") or None
        created=datetime.now(UTC).isoformat();mid="iam-"+uuid.uuid4().hex
        unsigned={"schema":SCHEMA,"contract":CONTRACT,"manifest_id":mid,"scope_type":str(scope_type),"scope_id":str(scope_id),"range_start":range_start,"range_end":range_end,"root_hash":root,"previous_manifest_hash":prev_hash,"signature_algorithm":"Ed25519","signature_key_version":ver,"public_key_sha256":_sha(pub),"metadata":dict(metadata or {}),"created_at":created}
        body=_canon(unsigned);mh=_sha(body);sig=base64.b64encode(priv.sign(body)).decode("ascii")
        manifest={**unsigned,"manifest_hash":mh,"signature_b64":sig}
        name=f"anchor-{created.replace(':','').replace('+','_')}-{mid[-12:]}.json";path=self.anchor_root/name;_write(path,manifest)
        return {**manifest,"external_anchor_ref":str(path)}
    def try_anchor(self,**kw:Any)->dict[str,Any]:
        try:return {"state":"ANCHORED","anchored":True,"canonical_write_blocked":False,"manifest":self.create_anchor(**kw)}
        except (OSError,PermissionError,RuntimeError) as e:return {"state":"DEGRADED","anchored":False,"canonical_write_blocked":False,"error_type":type(e).__name__,"error":str(e)[:500]}
    def verify_manifest(self,path:str|Path,*,expected_previous_hash:str|None=None)->dict[str,Any]:
        try:
            m=json.loads(Path(path).read_text(encoding="utf-8-sig"));u={k:v for k,v in m.items() if k not in {"manifest_hash","signature_b64"}};body=_canon(u)
            mh=_sha(body)==str(m.get("manifest_hash") or "");priv=self._private(int(m["signature_key_version"]));pk=priv.public_key();pubok=_sha(self._pub(priv))==str(m.get("public_key_sha256") or "")
            try:pk.verify(base64.b64decode(str(m["signature_b64"]),validate=True),body);sig=pubok
            except (InvalidSignature,ValueError):sig=False
            chain=expected_previous_hash is None or str(m.get("previous_manifest_hash") or "")==str(expected_previous_hash)
            return {"valid":mh and sig and chain,"manifest_hash_valid":mh,"signature_valid":sig,"chain_link_valid":chain,"detail":"ok" if mh and sig and chain else "verification failed"}
        except (OSError,KeyError,ValueError,TypeError,json.JSONDecodeError) as e:return {"valid":False,"manifest_hash_valid":False,"signature_valid":False,"chain_link_valid":False,"detail":f"{type(e).__name__}:{e}"}
    def verify_chain(self)->dict[str,Any]:
        paths=sorted(self.anchor_root.glob("anchor-*.json")) if self.anchor_root.is_dir() else [];prev=None;checks=[];ok=True
        for path in paths:
            c=self.verify_manifest(path,expected_previous_hash=prev);checks.append({"path":str(path),**c});ok=ok and bool(c["valid"])
            if c["valid"]:prev=str(json.loads(path.read_text(encoding="utf-8-sig"))["manifest_hash"])
        return {"ok":ok,"count":len(paths),"head":prev,"checks":checks}
