from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT=Path(r"C:\New Projet\MEMORIA-PERMANENTE")
ADAPTER=Path(r"C:\New Projet\MEMORIA-CLIENT-ADAPTER")
GOV=Path(r"C:\New Projet\GOVERNADOR-WINDOWS")
EVID=ROOT/'evidence'

def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def tree_source()->str:
    parts=[]
    for p in sorted((ADAPTER/'src/memoria_client_adapter').glob('*.py'),key=lambda x:x.name.lower()):
        parts.append(p.name+':'+sha(p))
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()

def main()->int:
    live=json.loads((EVID/'UNIVERSAL_ADAPTER_LIVE_PROOF.json').read_text(encoding='utf-8'))
    trust=json.loads((GOV/'config/memory-client-adapter.json').read_text(encoding='utf-8'))
    cfg=json.loads((GOV/'config/governor.json').read_text(encoding='utf-8-sig'))
    runtime=(GOV/'src/governor_windows/runtime_components.py').read_text(encoding='utf-8-sig')
    adapter_source='\n'.join(p.read_text(encoding='utf-8-sig') for p in (ADAPTER/'src/memoria_client_adapter').glob('*.py')).lower()
    wheel=ADAPTER/'dist'/trust['wheel']
    checks={
        'ADAPTER_SEPARATE_ROOT':ADAPTER.exists() and ADAPTER!=ROOT and ADAPTER!=GOV,
        'ADAPTER_IS_GIT_REPOSITORY':(ADAPTER/'.git').exists(),
        'ADAPTER_WHEEL_EXISTS':wheel.exists(),
        'WHEEL_SHA256_MATCH':wheel.exists() and sha(wheel).upper()==str(trust['wheel_sha256']).upper(),
        'INSTALLED_TREE_MANIFEST_MATCH':tree_source()==str(trust['installed_tree_sha256']),
        'NO_CONSUMER_SPECIFIC_CODE':all(x not in adapter_source for x in ('governor-windows','wmcp','chatgpt')),
        'NO_MEMORY_INTERNAL_IMPORT':'memory_permanent' not in adapter_source,
        'NO_DIRECT_MEMORY_DB_COUPLING':all(x not in adapter_source for x in ('psycopg','memory_database_url','55436','pgpass.conf')),
        'REMOTE_HTTP_FORBIDDEN':'non-loopback Memory endpoint requires HTTPS' in (ADAPTER/'src/memoria_client_adapter/client.py').read_text(encoding='utf-8'),
        'ACTIVE_CONSUMER_IMPORTS_UNIVERSAL':'from memoria_client_adapter import' in runtime,
        'NO_GOVERNOR_LOCAL_ADAPTER':not (GOV/'src/governor_windows/memory_client_adapter.py').exists(),
        'CONSUMER_DEPENDENCY_PINNED':'memoria-client-adapter==1.0.0' in (GOV/'pyproject.toml').read_text(encoding='utf-8'),
        'PUBLIC_ENDPOINT':str((cfg.get('memory_gateway') or {}).get('endpoint') or '').startswith(('http://','https://')),
        'ADAPTER_TRUST_CONFIGURED':str((cfg.get('memory_gateway') or {}).get('adapter_trust') or '')=='config/memory-client-adapter.json',
        'LIVE_INTEGRATION_PASS':live.get('UNIVERSAL_ADAPTER_PROVEN') is True and not live.get('failed_checks'),
    }
    failed=[k for k,v in checks.items() if not v]
    result={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'priority':'P5','objective':'UNIVERSAL_MEMORY_CLIENT_ADAPTER','adapter_root':str(ADAPTER),'adapter_version':'1.0.0','wheel':str(wheel),'wheel_sha256':sha(wheel) if wheel.exists() else None,'tree_sha256':tree_source(),'checks':checks,'failed_checks':failed,'P5_UNIVERSAL_CLIENT_ADAPTER_PROOF':'PASS' if not failed else 'FAIL','UNIVERSAL_CLIENT_ADAPTER_PROVEN':not failed}
    (EVID/'P5_UNIVERSAL_CLIENT_ADAPTER_PROOF.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (EVID/'P5_UNIVERSAL_CLIENT_ADAPTER_PROOF.md').write_text('# P5 - Universal Memory Client Adapter\n\n**P5:** '+result['P5_UNIVERSAL_CLIENT_ADAPTER_PROOF']+'\n\n'+'\n'.join(f'- {k}: {"PASS" if v else "FAIL"}' for k,v in checks.items())+'\n',encoding='utf-8')
    print(json.dumps({'P5':result['P5_UNIVERSAL_CLIENT_ADAPTER_PROOF'],'failed':failed,'wheel_sha256':result['wheel_sha256'],'tree_sha256':result['tree_sha256']},indent=2))
    return 0 if not failed else 1

if __name__=='__main__': raise SystemExit(main())
