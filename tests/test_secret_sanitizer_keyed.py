from memory_permanent.secret_sanitizer import SecretSanitizer


class FakeVault:
    def __init__(self):
        self.values=[]
    def put(self, *, tenant_id: str, secret: str, kind: str) -> str:
        self.values.append((tenant_id,secret,kind))
        return f'vault://memory/{tenant_id.lower()}/' + ('a'*24)


def test_key_aware_secret_fields_are_replaced_even_without_text_pattern():
    vault=FakeVault()
    sanitizer=SecretSanitizer(vault,'TENANT_A')
    sanitizer.refs=[]
    value=sanitizer.sanitize({'password':'plain-secret-value','nested':{'api_key':'opaque-token-value'}})
    assert value['password'].startswith('vault://memory/tenant_a/')
    assert value['nested']['api_key'].startswith('vault://memory/tenant_a/')
    assert [x[1] for x in vault.values] == ['plain-secret-value','opaque-token-value']


def test_non_sensitive_field_is_not_vaulted_without_secret_pattern():
    vault=FakeVault()
    sanitizer=SecretSanitizer(vault,'TENANT_A')
    value=sanitizer.sanitize({'note':'ordinary value'})
    assert value == {'note':'ordinary value'}
    assert vault.values == []


def test_common_unlabeled_secret_formats_are_vaulted():
    vault=FakeVault()
    sanitizer=SecretSanitizer(vault,'TENANT_A')
    samples={
        'github':'ghp_' + ('A'*36),
        'slack':'xoxb-' + ('1'*12) + '-' + ('2'*12) + '-' + ('A'*24),
        'google':'AIza' + ('A'*35),
        'stripe':'sk_live_' + ('A'*24),
        'jwt':'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.' + ('A'*32),
        'aws_access':'AKIA' + ('A'*16),
    }
    for raw in samples.values():
        clean=sanitizer.sanitize(raw)
        assert raw not in clean
        assert 'vault://memory/tenant_a/' in clean


def test_database_url_password_is_vaulted_without_losing_url_shape():
    vault=FakeVault()
    sanitizer=SecretSanitizer(vault,'TENANT_A')
    raw='postgresql://user:Passw0rd@localhost/db'
    clean=sanitizer.sanitize(raw)
    assert 'Passw0rd' not in clean
    assert clean.startswith('postgresql://user:vault://memory/tenant_a/')
    assert clean.endswith('@localhost/db')
    assert ('TENANT_A','Passw0rd','database_password') in vault.values


def test_additional_sensitive_key_names_are_vaulted():
    vault=FakeVault()
    sanitizer=SecretSanitizer(vault,'TENANT_A')
    value=sanitizer.sanitize({
        'secret_key':'opaque-secret',
        'aws_secret_access_key':'opaque-aws-secret',
        'github_token':'opaque-github-token',
        'database_url':'postgresql://u:p@h/db',
    })
    assert all(str(v).startswith('vault://memory/tenant_a/') for v in value.values())
