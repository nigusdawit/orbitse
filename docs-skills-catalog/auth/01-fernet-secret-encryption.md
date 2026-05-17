# Fernet Secret Encryption at Rest

One-line: Encrypt admin-supplied API keys, connection strings, and other small secrets in the database using a Fernet key deterministically derived from the app's session secret.

Category: Auth & Multi-tenancy

## When to use
- The admin paste-boxes credentials for a third-party service (Postgres URL, REST token, OAuth client secret, MCP server token, AI provider key) and your app stores them in its own database.
- You want round-trippable values (the app needs the plaintext later to call out), so password-style one-way hashing is wrong.
- You do not want to ask the operator to manage a separate KMS key — the existing session-signing secret is good enough as a derivation source.
- The blast radius is "anyone with a DB dump but no app secret cannot read these values."

Do NOT use this for:
- User passwords (use a password hash like bcrypt/argon2).
- Anything regulated (PCI/PHI). This is at-rest obfuscation, not a compliance-grade vault.
- Large blobs. Fernet encrypts to base64 with a per-message IV — fine for tokens, not files.

## Architecture
1. A single helper (`_get_fernet()`) resolves the app's session secret, sha256-digests it to 32 bytes, base64-encodes it, and constructs a `cryptography.fernet.Fernet` instance.
2. Two public helpers (`encrypt_secret(plaintext) -> str`, `decrypt_secret(token) -> str`) wrap encrypt/decrypt. `decrypt_secret` swallows `InvalidToken`/`ValueError` and returns an empty string so a bad row never crashes the calling endpoint.
3. Tables that hold credentials store the Fernet token in a plain `TEXT` column (typically named `encrypted_*` or `api_key`).
4. Read paths call `decrypt_secret(row["..."])` only at the moment of provider call. Write paths call `encrypt_secret(value)` once and never store the raw value alongside.

The Fernet key is **deterministic per app instance** — same session secret yields the same key — so encrypted blobs survive process restarts as long as the secret survives.

## Data model
No dedicated tables. Encrypted columns appear inline on the owning table, for example:
- `agent_provider_settings.api_key TEXT` — encrypted OpenAI/Anthropic key.
- `external_data_connections.encrypted_config TEXT` — encrypted JSON connection blob.
- Any future "paste your API key" column should follow the same convention and be named `encrypted_*` for greppability.

## API surface
Internal Python only — there is no HTTP surface for the cipher itself.
- `encrypt_secret(plaintext: str | None) -> str` — returns base64 Fernet token, or `""` for `None`.
- `decrypt_secret(token: str) -> str` — returns plaintext, or `""` on any decrypt failure.
- `_get_fernet()` — internal; do not call from route handlers.

## Key files in this codebase
- `app.py` — `_get_fernet`, `encrypt_secret`, `decrypt_secret` (~lines 880–919).
- `app.py` — example callers around `agent_provider_settings` and `external_data_connections` (`encrypt_secret(config ...)`, `decrypt_secret(row.get("encrypted_config", ""))`).

## External dependencies
- Python: `cryptography` (`from cryptography.fernet import Fernet, InvalidToken`).
- Stdlib: `hashlib`, `base64`, `os`.

## Pitfalls
- **Key rotation is not implemented.** If the operator rotates `FLASK_SECRET_KEY`, every previously-encrypted blob becomes unreadable and `decrypt_secret` will silently return `""`. Plan for either pinning the secret or building an explicit re-encrypt pass before rotating.
- **Fallback chain hides config errors.** `_get_fernet()` walks env var → local `.flask_secret` file → a hard-coded `"dev-fallback-secret-replace-me"` literal. The literal fallback means encrypted columns will appear to work in a misconfigured environment, then become unreadable the moment a real secret is set. Log/alert if you take the third branch.
- **Empty string is overloaded.** `decrypt_secret` returns `""` for both "no token stored" and "decrypt failed." Callers that need to distinguish must check before decrypting.
- **Not authenticated against the row.** Fernet binds nothing to the owning row id — copying a ciphertext from one row to another succeeds. If that matters, include the row id in the plaintext before encrypting.
- **At-rest only.** Anyone who can read the running process memory or trip a log line that prints the decrypted value still gets the secret.

## Adaptation notes
- Swap the derivation source: any 32 bytes of secret entropy will do (`os.urandom`, a KMS-fetched DEK, a passphrase + PBKDF2). For multi-app deployments, derive per-app keys from a master secret + app id.
- Migrating to a real KMS: replace `_get_fernet()` body with an SDK call (AWS KMS Encrypt/Decrypt, GCP KMS, HashiCorp Vault transit). Keep the `encrypt_secret`/`decrypt_secret` surface identical so call sites never change.
- If you need authenticated context, include the table name + row id in the plaintext JSON before encrypting (cheap binding) or move to AES-GCM with associated data.

## Cross-references
- `02-multi-tenant-scaffolding.md` — every `agent_provider_settings` row is conceptually per-tenant; combine with `current_tenant_id()` when scaling out.
- `03-admin-gate.md` — the same `FLASK_SECRET_KEY` that signs admin session cookies derives the Fernet key. Treat them as one secret with two uses.
