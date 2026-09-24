# Security Hardening — 2026-09-01

Correções abertas após revisão de fechamento da V4:

1. Inicializar repositório Git e política `.gitignore` fail-safe.
2. Declarar `cryptography` como dependência de runtime.
3. Remover chave-mestra e vault criptografado da árvore física do produto.
4. Migrar chave para Windows DPAPI + ACL em `%ProgramData%\MemoriaPermanente\vault`.
5. Introduzir autenticação criptográfica para identidade/escopo da API; headers de identidade não podem ser autoafirmados.
6. Manter bind padrão em `127.0.0.1`; exposição não-loopback deve ser fail-closed sem transporte seguro.
7. Retestar gates impactados M3, M5 e M10 antes da aceitação global V4.
