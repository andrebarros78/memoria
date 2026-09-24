$ErrorActionPreference = 'Stop'
$root = 'C:\New Projet\MEMORIA-PERMANENTE'
Set-Location $root
$env:PYTHONPATH = "$root\src"
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$pyScript = @"
from __future__ import annotations
import json, sys, urllib.request, urllib.error
import psycopg
from memory_permanent.client_auth import ClientRegistry, sign_headers

def req(method: str, url: str, path: str, signed: bool=False):
    headers={}
    if signed:
        _, secret = ClientRegistry().get('local-admin')
        headers=sign_headers(client_id='local-admin', secret=secret, method=method, path_query=path, body=b'')
    request=urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data=response.read().decode('utf-8','replace')
            return {'status': response.status, 'body_len': len(data), 'sample': data[:120]}
    except urllib.error.HTTPError as exc:
        return {'status': exc.code, 'body_len': 0, 'sample': exc.reason}

out={}
out['v4_health']=req('GET','http://127.0.0.1:8787/health','/health')
out['rc1_health']=req('GET','http://127.0.0.1:8792/health','/health')
out['rc1_metrics_unsigned']=req('GET','http://127.0.0.1:8792/metrics','/metrics')
out['rc1_metrics_signed']=req('GET','http://127.0.0.1:8792/metrics','/metrics', signed=True)
with psycopg.connect('postgresql://postgres@127.0.0.1:55436/memoria_permanente') as c:
    out['v4_trace_count']=int(c.execute('select count(*) from retrieval_traces').fetchone()[0])
with psycopg.connect('postgresql://postgres@127.0.0.1:55436/memoria_permanente_v52_rc1') as c:
    out['rc1_trace_count']=int(c.execute('select count(*) from retrieval_traces').fetchone()[0])
    row=c.execute('select trace_id,retrieval_modes from retrieval_traces order by created_at desc limit 1').fetchone()
    out['rc1_latest_trace']=[row[0], row[1]] if row else None
out['fallback']='SIGNED_API_METRICS_PLUS_RC1_RETRIEVAL_TRACES'
out['phoenix_parallel']='BLOCKED_BY_MULTIPLE_INSTANCE_STARTUP_ON_THIS_HOST'
print(json.dumps(out, indent=2, default=str))
ok = (
    out['v4_health']['status']==200 and
    out['rc1_health']['status']==200 and
    out['rc1_metrics_unsigned']['status']==401 and
    out['rc1_metrics_signed']['status']==200 and
    out['rc1_trace_count'] > out['v4_trace_count']
)
sys.exit(0 if ok else 2)
"@
$tmp = Join-Path $root '.agents\rc1_observability_validate_runtime.py'
[IO.File]::WriteAllText($tmp, $pyScript, (New-Object Text.UTF8Encoding($false)))
& "$root\runtime\api-clean\Scripts\python.exe" $tmp
$code = $LASTEXITCODE
Remove-Item $tmp -Force -ErrorAction SilentlyContinue
Write-Output ('OBSERVABILITY_FALLBACK_EXIT=' + $code)
exit $code