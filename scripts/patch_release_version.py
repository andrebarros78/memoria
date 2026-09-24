from pathlib import Path

root=Path(r'C:\RMP18\repo-base023')
p=root/'pyproject.toml';c=p.read_text(encoding='utf-8');c=c.replace('version = "0.23.0"','version = "0.26.1"',1);p.write_text(c,encoding='utf-8')
p=root/'src/memory_permanent/api.py';c=p.read_text(encoding='utf-8');c=c.replace('version="0.26.0"','version="0.26.1-recovery"',1).replace('"version": "0.23.0"','"version": "0.26.1-recovery"',1);p.write_text(c,encoding='utf-8')
for p in (root/'tests').glob('test_*.py'):
 c=p.read_text(encoding='utf-8');c=c.replace('app.version == "0.26.0"','app.version == "0.26.1-recovery"').replace("app.version=='0.26.0'","app.version=='0.26.1-recovery'");p.write_text(c,encoding='utf-8')
print('release version patched')