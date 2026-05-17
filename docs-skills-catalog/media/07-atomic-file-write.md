# Atomic file write — `.part` + `os.replace`

## When to use
Any time you write a file that:
- another request might read concurrently (cache files, generated audio, snapshot exports), OR
- the process might be killed mid-write (deploy SIGTERM, crash, OOM kill), AND
- a half-written file would be silently corrupt to readers (binary formats, JSON the next boot will load, env files).

The classic foot-gun: a reader opens the file just after `open(..., "wb")` truncated it but before any bytes were written, and gets an empty buffer that looks like a valid empty file.

## Architecture
Two-step write under a unique-per-request scratch path:

1. Write all bytes to `<final>.part-<unique>` (or any sibling temp path on the same filesystem).
2. On success, call `os.replace(tmp, final)` — POSIX-atomic on the same filesystem; the final path either points at the OLD bytes or the NEW bytes, never an intermediate.
3. On any error or client disconnect, `os.remove(tmp)` to clean up the scratch file.

Two scenarios in this codebase:

- **Streaming TTS cache** (`/api/voice/tts/stream/consume`): provider bytes are piped straight to the client AND tee'd to `<hash>.mp3.part-<request_id>`. On clean EOF, `os.replace` promotes it to the cache filename. On disconnect or provider error, the `.part` is removed. The unique suffix per request prevents two concurrent generations of the same hash from clobbering each other's scratch files.
- **Env-file / settings writes** (`env_manager.py`): the admin-managed `.env` and `settings.json` files are rewritten the same way — temp file, `fsync` optionally, then `os.replace`. A crash mid-write can never leave a half-parsed env file that would prevent the next boot.

## Data model
None — pattern only.

## API surface
Pure Python:
```
tmp = f"{final}.part-{uuid4().hex}"
with open(tmp, "wb") as f:
    f.write(data)        # or stream chunk-by-chunk
    f.flush(); os.fsync(f.fileno())   # optional, for crash-safety on power loss
os.replace(tmp, final)   # atomic on same filesystem
```
On any exception path: `os.remove(tmp)` inside a `try/except FileNotFoundError`.

## Key files
- `env_manager.py:299` — atomic `.env` write.
- `env_manager.py:401` — atomic `settings.json` write.
- TTS streaming consume endpoint in `app.py` (search for `tts/stream/consume`) — atomic cache promotion (the in-tree implementation currently uses an `io.BytesIO` buffer + single `storage.write_bytes` call, which gives the same atomicity property because `write_bytes` itself does not partially expose a key).

## External deps
None — `os.replace` and `os.fsync` are stdlib.

## Pitfalls
- **`os.replace` is only atomic on the same filesystem.** Writing the `.part` to `/tmp` then replacing into `/uploads` may silently fall back to a non-atomic copy on some OS/FS combos. Always place the temp file next to the final path.
- **Windows note**: `os.replace` is atomic on Windows too (unlike `os.rename`, which fails if the target exists). Use `os.replace`, never `os.rename`, for this pattern.
- **Unique suffix per request** matters for the cache scenario: without it, two concurrent writers for the same key race for the same `.part` file and one will truncate the other's bytes.
- `os.fsync` is only needed if you care about surviving a power loss (not just a process kill). It's expensive on spinning disks; skip it for cache files where regeneration on next boot is cheap.
- Clean up `.part-*` orphans on startup with a glob sweep if your scratch files live in a long-lived directory — disconnects can leak them, especially under SIGKILL.
- Don't try to be clever with `tempfile.NamedTemporaryFile(delete=False)` cross-directory — it picks `$TMPDIR` by default. Build the temp path yourself, sibling to the final.

## Adaptation notes
- For object storage (S3), the equivalent is "upload to a temporary key then `copy_object` + `delete_object`", or simply rely on S3's per-object atomicity for single-PUT writes (multipart uploads have their own atomic semantics).
- For very large streams, prefer `os.fdopen(os.open(tmp, O_WRONLY|O_CREAT|O_EXCL, 0o600))` to combine atomic create + strict perms in one syscall.

## Adoption checklist
- [ ] Audit every `open(path, "wb")` that writes user-visible or boot-time files.
- [ ] Pick a `.part-<unique>` suffix scheme (uuid4 hex is fine).
- [ ] Ensure scratch + final live on the same filesystem.
- [ ] Wrap in try/except that removes the temp file on failure.
- [ ] Add a startup sweep for orphaned `.part-*` files if relevant.
- [ ] Decide per call site whether `fsync` is worth it.
