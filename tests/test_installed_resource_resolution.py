
from memory_permanent import migration_runner, product_dna


def test_migrations_resolve_from_pip_target_sibling_share(tmp_path, monkeypatch):
    module=tmp_path/'memory_permanent'/'migration_runner.py'
    module.parent.mkdir(parents=True)
    module.write_text('',encoding='utf-8')
    target=tmp_path/'share'/'memoria-permanente'/'migrations'
    target.mkdir(parents=True)
    (target/'0044_trigger_security_definer_hardening.sql').write_text('-- proof',encoding='utf-8')
    monkeypatch.setattr(migration_runner,'__file__',str(module))
    assert migration_runner.default_migrations_dir()==target

def test_product_dna_resolves_from_pip_target_sibling_share(tmp_path, monkeypatch):
    module=tmp_path/'memory_permanent'/'product_dna.py'
    module.parent.mkdir(parents=True)
    module.write_text('',encoding='utf-8')
    target=tmp_path/'share'/'memoria-permanente'/'.wmcp'/'product-dna.json'
    target.parent.mkdir(parents=True)
    target.write_text('{}',encoding='utf-8')
    monkeypatch.setattr(product_dna,'__file__',str(module))
    assert product_dna.product_dna_path()==target
