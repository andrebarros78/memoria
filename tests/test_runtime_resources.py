from memory_permanent.migration_runner import default_migrations_dir
from memory_permanent.product_dna import product_dna_path


def test_runtime_resources_resolve_in_source_tree():
    dna = product_dna_path()
    migrations = default_migrations_dir()
    migration_files = sorted(migrations.glob("*.sql"))
    assert dna.name == "product-dna.json" and dna.is_file()
    assert migration_files
    assert migration_files[0].name == "0001_base.sql"
    assert all(path.is_file() for path in migration_files)
