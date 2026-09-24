param([string]$OutputDir = "")
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Python=Join-Path $Root '.venv\Scripts\python.exe'
if(-not $OutputDir){$OutputDir=Join-Path $Root 'runtime\release-wheel'}
$epoch='1704067200'
$previousEap=$ErrorActionPreference
try {
  $ErrorActionPreference='SilentlyContinue'
  $candidate=(& git -C $Root show -s --format=%ct HEAD 2>$null | Select-Object -First 1)
  if($LASTEXITCODE -eq 0 -and $candidate){$epoch=([string]$candidate).Trim()}
} catch { } finally { $ErrorActionPreference=$previousEap }
$env:SOURCE_DATE_EPOCH=([string]$epoch).Trim()
Remove-Item -Recurse -Force (Join-Path $Root 'build') -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $OutputDir | Out-Null
Remove-Item -Force (Join-Path $OutputDir '*.whl') -ErrorAction SilentlyContinue
& $Python -m build --wheel --outdir $OutputDir
if($LASTEXITCODE -ne 0){throw "wheel build failed rc=$LASTEXITCODE"}
$wheel=Get-ChildItem (Join-Path $OutputDir '*.whl') | Select-Object -First 1
if(-not $wheel){throw 'wheel not produced'}
$check=@"
from pathlib import Path
import zipfile,hashlib,json,sys
w=Path(r'$($wheel.FullName)')
with zipfile.ZipFile(w) as z:
    names=sorted(z.namelist())
    forbidden=[n for n in names if (('governor_contract' in n.lower() and '/share/memoria-permanente/migrations/' not in n.lower()) or n.lower().endswith(('.key','.pem','.p12','.pfx','.dpapi')) or '/runtime/' in n.lower() or '/backups/' in n.lower())]
    required_assets=['memory_permanent/static/index.html','memory_permanent/static/app.js','memory_permanent/static/styles.css']
    missing_assets=[n for n in required_assets if n not in names]
    dna=[n for n in names if n.endswith('share/memoria-permanente/.wmcp/product-dna.json')]
    migrations=[n for n in names if '/share/memoria-permanente/migrations/' in n and n.endswith('.sql')]
    source_migrations=list(Path(r'$Root').joinpath('migrations').glob('*.sql'))
    expected_migrations=len(source_migrations)
    resource_ok=(not missing_assets and len(dna)==1 and len(migrations)==expected_migrations)
    clean=(not forbidden and resource_ok)
    result={'wheel':w.name,'bytes':w.stat().st_size,'sha256':hashlib.sha256(w.read_bytes()).hexdigest(),'entries':len(names),'forbidden_entries':forbidden,'missing_assets':missing_assets,'product_dna_files':len(dna),'migration_files':len(migrations),'expected_migration_files':expected_migrations,'resource_ok':resource_ok,'clean':clean,'source_date_epoch':r'$env:SOURCE_DATE_EPOCH'}
print(json.dumps(result,indent=2))
sys.exit(0 if clean else 2)
"@
$check | & $Python -
if($LASTEXITCODE -ne 0){throw 'wheel content verification failed'}
Remove-Item -Recurse -Force (Join-Path $Root 'build') -ErrorAction SilentlyContinue

