from pathlib import Path

p=Path(r'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\scripts\prove_memoria_plus_p15_recovery.ps1')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("$restoreLog=Join-Path $root ('runtime\\p15-restore-'+$stamp+'.log')", "$restoreLog=Join-Path $root ('runtime\\p15-restore-'+$stamp+'.log')\n$serverLog=Join-Path $root ('runtime\\p15-postgres-'+$stamp+'.log')")
s=s.replace("& (Join-Path $pg 'pg_ctl.exe') -D $data -w -t 30 start *>> $restoreLog", "& (Join-Path $pg 'pg_ctl.exe') -D $data -l $serverLog -w -t 30 start | Out-Null")
s=s.replace("& (Join-Path $pg 'pg_ctl.exe') -D $data -m fast -w -t 30 stop *>> $restoreLog; Step 'STOP_END'", "& (Join-Path $pg 'pg_ctl.exe') -D $data -m fast -w -t 30 stop | Out-Null; Step 'STOP_END'")
s=s.replace("Remove-Item $restoreLog -Force -ErrorAction SilentlyContinue", "Remove-Item $restoreLog -Force -ErrorAction SilentlyContinue\n    Remove-Item $serverLog -Force -ErrorAction SilentlyContinue")
p.write_text(s,encoding='utf-8',newline='\n')
print('patched')
