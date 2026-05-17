# Pluggable storage layer (local ↔ S3)

## When to use
A Flask app that today writes uploads to the local filesystem but needs to survive ephemeral filesystems (Replit, Fly machines, container PaaS) or multi-worker deployments behind a load balancer where one worker writes and another reads. You want to flip to S3-compatible storage (AWS S3, Cloudflare R2, MinIO, Wasabi, Backblaze B2) without rewriting upload sites.

## Architecture
A single module exposes a backend-agnostic interface. Two implementations satisfy it:

- `_LocalStorage` — byte-for-byte the original on-disk path, default.
- `_S3Storage` — boto3 against any S3-compatible bucket, plus a **legacy disk fallback** on reads.

A `get_storage()` singleton picks the backend from `UPLOADS_BACKEND` (default `local`) at first call. All call sites use it via the `write_bytes / write_fileobj / read_bytes / exists / size / delete / serve / url_for` surface.

Subpath convention:
- `"abc.jpg"` → root of `uploads/`
- `"voice/<hash>.mp3"` → TTS cache subdir
- `"contracts/<id>.pdf"` → contracts subdir

The S3 backend treats subpaths as object keys directly. Reads (`read_bytes`, `exists`, `serve`) check S3 first and **only on a real NoSuchKey** fall back to the legacy on-disk path — so an operator can flip the env var today, all existing files keep serving, and a one-shot migration script can copy them across later. Any other S3 error (auth, region typo, network) re-raises so misconfiguration surfaces immediately.

`serve()` always returns a Flask `Response`, so existing `/uploads/<file>` URLs work unchanged. Set `UPLOADS_PUBLIC_BASE_URL` and `url_for()` returns a CDN URL directly to bypass the proxy.

## Data model
None — the storage module owns the bytes; the DB just stores filenames.

## API surface
Programmatic (Python):
- `storage.get_storage().write_bytes(subpath, data, content_type=...)`
- `storage.get_storage().write_fileobj(subpath, file_like, content_type=...)`
- `storage.get_storage().read_bytes(subpath) -> Optional[bytes]`
- `storage.get_storage().exists(subpath) -> bool`
- `storage.get_storage().size(subpath) -> Optional[int]`
- `storage.get_storage().delete(subpath)`
- `storage.get_storage().serve(subpath, mimetype=...) -> Response`
- `storage.get_storage().url_for(subpath) -> str`

Env vars:
- `UPLOADS_BACKEND` — `local` (default) or `s3`
- `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
- `S3_ENDPOINT_URL` (for R2/MinIO/etc.), `S3_FORCE_PATH_STYLE`
- `UPLOADS_PUBLIC_BASE_URL` (CDN prefix that bypasses the Flask proxy)

## Key files
- `storage.py` — entire module (~370 lines).
- `storage.py:83` — `_check_safe_subpath()` path-traversal guard.
- `storage.py:123` — `_LocalStorage` implementation.
- `storage.py:194` — `_S3Storage` implementation with legacy fallback.
- `storage.py:354` — `get_storage()` singleton.

## External deps
- `boto3` + `botocore` (only imported lazily inside `_S3Storage.__init__`, so projects that never enable S3 don't pay the import cost or ship the dependency on cold paths).
- Flask `send_file` / `send_from_directory` for the local backend.

## Pitfalls
- **Don't double-write.** S3 writes are S3-only; don't keep mirroring to disk "just in case" — eventual divergence is worse than a single source of truth.
- **Fail loud on misconfiguration.** Only `NoSuchKey` should fall back to disk; anything else (403, 503, DNS) must raise. Otherwise a wrong-region cutover silently regenerates expensive TTS audio on every request.
- Always run subpaths through `_check_safe_subpath()` — even though they come from app code, one careless concat can become an FS-escape on the local backend.
- boto3 clients are thread-safe per AWS docs; one singleton per process is correct, do not create per-request clients.
- If you set `UPLOADS_PUBLIC_BASE_URL`, the bucket must be public-read OR the URL must be a CDN with the right origin auth — bypassing the proxy means no app-level auth.

## Adaptation notes
- Add a `gcs` backend by writing a third class with the same surface; nothing else changes.
- For very large objects, switch `read_bytes` to a streaming `read_stream` to avoid materialising the body in memory.
- Generate presigned PUT URLs for direct browser uploads to S3 by adding a `presign_put(subpath)` method.
- Keep the subpath convention small and well-known — `voice/`, `contracts/` — instead of letting every feature invent its own folder.

## Adoption checklist
- [ ] Replace every direct `open(uploads_path, 'wb')` with `storage.write_bytes` or `write_fileobj`.
- [ ] Replace every `send_from_directory(uploads_root, name)` with `storage.serve(name)`.
- [ ] Add the env-var docs to your runbook.
- [ ] Decide and document the subpath convention before second-feature drift sets in.
- [ ] When flipping to S3 in production, deploy with the legacy disk fallback live and run a background migration of pre-cutover files.
