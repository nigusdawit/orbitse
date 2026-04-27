"""
Pluggable upload storage backend (Tier 9, April 2026).

The app stores three kinds of binary content on disk today:

  * `uploads/<file>`           — operator-uploaded media (images, videos, audio)
                                 plus deck-import page renders
  * `uploads/voice/<file>`     — TTS audio cache (regenerable from OpenAI/ElevenLabs)
  * `uploads/contracts/<file>` — operator-uploaded contract PDFs

That works fine on a single-pod dev box but breaks on every deploy target
with an ephemeral filesystem (Replit, container-style PaaS, Fly machines
that get rebuilt) and on any multi-worker gunicorn deployment behind a
load balancer (one worker writes, the next request hits a different worker
that can't read it back).

This module hides the storage backend behind one stable API. Default
behaviour is unchanged from the original on-disk implementation —
`UPLOADS_BACKEND=local` (the default) is byte-for-byte the legacy code
path. Set `UPLOADS_BACKEND=s3` and the backend switches to any
S3-compatible bucket: AWS S3, Cloudflare R2, MinIO, Wasabi, Backblaze B2,
or anything else that speaks the S3 API.

Subpath convention
------------------
Storage keys are passed as relative subpaths:

  * `"abc123.jpg"`          → root of uploads/
  * `"voice/hash.mp3"`      → TTS cache
  * `"contracts/abc.pdf"`   → contract PDF

The backend translates this to the right disk path (local) or S3 key (s3).

S3 backend behaviour
--------------------
* Reads (`read_bytes`, `exists`, `serve`) check S3 first. On a NoSuchKey
  miss they fall back to the legacy on-disk path. This means an operator
  can flip `UPLOADS_BACKEND=s3` today, all existing files keep serving
  from disk, and a one-shot migration script (see follow-up tasks) can
  catch them up in the background.
* Writes always go to S3 only — no double-write to disk.
* `serve()` always returns a Flask Response. By default it streams the
  body back through Flask so the existing `/uploads/<file>` URLs keep
  working unchanged (no DB row rewrites needed). Set
  `UPLOADS_PUBLIC_BASE_URL` to bypass the proxy and serve directly from
  a public-read bucket / CDN.

Environment variables
---------------------
  UPLOADS_BACKEND          "local" (default) or "s3"
  S3_BUCKET                required when backend=s3
  S3_REGION                default "us-east-1"
  S3_ENDPOINT_URL          optional — set this for R2/MinIO/etc.
                           e.g. https://<account>.r2.cloudflarestorage.com
  S3_ACCESS_KEY_ID         required when backend=s3
  S3_SECRET_ACCESS_KEY     required when backend=s3
  S3_FORCE_PATH_STYLE      "1" to force path-style URLs (some S3-compat
                           services require this)
  UPLOADS_PUBLIC_BASE_URL  optional CDN / public-bucket prefix used by
                           `url_for()` to bypass the Flask proxy.
                           Leave unset to keep the proxy URL scheme.

Threading
---------
The boto3 client is thread-safe per the AWS SDK docs, so a single
`get_storage()` singleton serves the whole Flask process.
"""

from __future__ import annotations

import io
import mimetypes
import os
from typing import Optional, Union

from flask import Response, send_file, send_from_directory


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_UPLOADS_ROOT = os.path.join(_BASE_DIR, "uploads")


def _check_safe_subpath(subpath: str) -> None:
    """Raise ValueError if the subpath looks like a path-traversal attempt.

    Storage subpaths come from app code (never raw user input), but defending
    against `..` and absolute paths is cheap and prevents a single misuse
    from turning into an FS-escape on the local backend."""
    if not isinstance(subpath, str) or not subpath:
        raise ValueError(f"Invalid storage subpath: {subpath!r}")
    if subpath.startswith("/") or subpath.startswith("\\"):
        raise ValueError(f"Refusing absolute storage subpath: {subpath!r}")
    parts = subpath.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        raise ValueError(f"Refusing storage subpath with '..': {subpath!r}")


def _local_path(subpath: str) -> str:
    """Return the absolute local path for a subpath after a safety check."""
    _check_safe_subpath(subpath)
    return os.path.join(_LOCAL_UPLOADS_ROOT, subpath)


def _ensure_local_dir(subpath: str) -> str:
    """Translate a storage subpath to an absolute local path, creating
    parent directories as needed so the caller can `open(...).write()`."""
    full = _local_path(subpath)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return full


def _content_type_for(subpath: str) -> str:
    ct, _ = mimetypes.guess_type(subpath)
    return ct or "application/octet-stream"


# ---------------------------------------------------------------------------
# Local backend — the original on-disk behaviour, behind the same API.
# ---------------------------------------------------------------------------

class _LocalStorage:
    name = "local"

    def write_bytes(self, subpath: str, data: bytes, *,
                    content_type: Optional[str] = None) -> None:
        path = _ensure_local_dir(subpath)
        with open(path, "wb") as f:
            f.write(data)

    def write_fileobj(self, subpath: str, fileobj, *,
                      content_type: Optional[str] = None) -> None:
        """Save a file-like object. Werkzeug FileStorage gets the fast
        path via its native .save(); raw IO objects get streamed in
        8 KB chunks so we don't need the whole body in memory."""
        path = _ensure_local_dir(subpath)
        save = getattr(fileobj, "save", None)
        if callable(save):
            save(path)
            return
        with open(path, "wb") as out:
            while True:
                chunk = fileobj.read(8192)
                if not chunk:
                    break
                out.write(chunk)

    def read_bytes(self, subpath: str) -> Optional[bytes]:
        path = _local_path(subpath)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def exists(self, subpath: str) -> bool:
        return os.path.exists(_local_path(subpath))

    def size(self, subpath: str) -> Optional[int]:
        try:
            return os.path.getsize(_local_path(subpath))
        except OSError:
            return None

    def delete(self, subpath: str) -> None:
        try:
            os.remove(_local_path(subpath))
        except (FileNotFoundError, IsADirectoryError):
            pass

    def serve(self, subpath: str, *, mimetype: Optional[str] = None) -> Response:
        """Return a Flask Response that serves the file. send_from_directory
        already does a safe-join and returns 404 for missing files; the
        explicit `_check_safe_subpath` is defence-in-depth that fails fast
        with a ValueError before any FS lookup."""
        _check_safe_subpath(subpath)
        if mimetype:
            return send_from_directory(_LOCAL_UPLOADS_ROOT, subpath, mimetype=mimetype)
        return send_from_directory(_LOCAL_UPLOADS_ROOT, subpath)

    def url_for(self, subpath: str) -> str:
        # Local backend always proxies through /uploads/<file> — same URL
        # scheme the app has used since day one, so no DB row rewrites.
        _check_safe_subpath(subpath)
        return f"/uploads/{subpath}"


# ---------------------------------------------------------------------------
# S3 backend — boto3 against any S3-compatible bucket. boto3 is imported
# lazily so projects that never enable S3 don't pay for it at module-import
# time (matters for the test suite, which boots the whole app per session).
# ---------------------------------------------------------------------------

class _S3Storage:
    name = "s3"

    def __init__(self):
        import boto3  # lazy
        from botocore.config import Config as _BotoConfig

        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            raise RuntimeError(
                "S3_BUCKET is not set — required when UPLOADS_BACKEND=s3")
        access_key = os.environ.get("S3_ACCESS_KEY_ID")
        secret_key = os.environ.get("S3_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            raise RuntimeError(
                "S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are required "
                "when UPLOADS_BACKEND=s3")

        region = os.environ.get("S3_REGION") or "us-east-1"
        endpoint = os.environ.get("S3_ENDPOINT_URL") or None
        force_path = (os.environ.get("S3_FORCE_PATH_STYLE", "")
                      .strip().lower() in ("1", "true", "yes"))

        cfg = _BotoConfig(
            region_name=region,
            s3={"addressing_style": "path" if force_path else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=30,
        )
        self._client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint,
            config=cfg,
        )
        self._bucket = bucket
        self._public_base = (os.environ.get("UPLOADS_PUBLIC_BASE_URL")
                             or "").rstrip("/")
        self._legacy = _LocalStorage()  # for read fallback during migration

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _is_not_found(exc) -> bool:
        from botocore.exceptions import ClientError
        if not isinstance(exc, ClientError):
            return False
        code = exc.response.get("Error", {}).get("Code", "") or ""
        # S3 returns NoSuchKey for missing objects; head_object returns 404.
        return code in ("NoSuchKey", "404", "NotFound")

    # -- writes -------------------------------------------------------------

    def write_bytes(self, subpath: str, data: bytes, *,
                    content_type: Optional[str] = None) -> None:
        _check_safe_subpath(subpath)
        self._client.put_object(
            Bucket=self._bucket,
            Key=subpath,
            Body=data,
            ContentType=content_type or _content_type_for(subpath),
        )

    def write_fileobj(self, subpath: str, fileobj, *,
                      content_type: Optional[str] = None) -> None:
        _check_safe_subpath(subpath)
        self._client.upload_fileobj(
            Fileobj=fileobj,
            Bucket=self._bucket,
            Key=subpath,
            ExtraArgs={"ContentType": content_type or _content_type_for(subpath)},
        )

    # -- reads (with legacy disk fallback) ----------------------------------
    #
    # Read paths fall back to the legacy on-disk store ONLY on a true
    # not-found from S3. Any other error (auth failure, wrong region,
    # endpoint typo, network outage) is re-raised so a misconfigured
    # cutover surfaces immediately instead of masquerading as a cache
    # miss and silently re-generating expensive content (TTS audio,
    # deck-import images) on every request.

    def read_bytes(self, subpath: str) -> Optional[bytes]:
        _check_safe_subpath(subpath)
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=subpath)
            return resp["Body"].read()
        except Exception as e:
            if self._is_not_found(e):
                return self._legacy.read_bytes(subpath)
            raise

    def exists(self, subpath: str) -> bool:
        _check_safe_subpath(subpath)
        try:
            self._client.head_object(Bucket=self._bucket, Key=subpath)
            return True
        except Exception as e:
            if self._is_not_found(e):
                return self._legacy.exists(subpath)
            raise

    def size(self, subpath: str) -> Optional[int]:
        _check_safe_subpath(subpath)
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=subpath)
            return int(resp.get("ContentLength") or 0)
        except Exception as e:
            if self._is_not_found(e):
                return self._legacy.size(subpath)
            raise

    def delete(self, subpath: str) -> None:
        _check_safe_subpath(subpath)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=subpath)
        except Exception as e:
            # delete_object on a missing key is a no-op in S3 (no error),
            # so any exception here is a real failure — surface it.
            if not self._is_not_found(e):
                raise
        # Also remove any legacy disk copy so a re-upload of the same key
        # doesn't accidentally serve a stale on-disk version.
        self._legacy.delete(subpath)

    def serve(self, subpath: str, *,
              mimetype: Optional[str] = None) -> Response:
        _check_safe_subpath(subpath)
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=subpath)
        except Exception as e:
            if self._is_not_found(e):
                return self._legacy.serve(subpath, mimetype=mimetype)
            raise
        body_bytes = resp["Body"].read()
        ct = mimetype or resp.get("ContentType") or _content_type_for(subpath)
        # Wrap in BytesIO so Flask's send_file can do range requests / etag.
        return send_file(
            io.BytesIO(body_bytes),
            mimetype=ct,
            download_name=os.path.basename(subpath),
            as_attachment=False,
        )

    def url_for(self, subpath: str) -> str:
        _check_safe_subpath(subpath)
        if self._public_base:
            return f"{self._public_base}/{subpath}"
        return f"/uploads/{subpath}"


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_BACKEND: Optional[Union[_LocalStorage, _S3Storage]] = None


def get_storage():
    """Return the singleton storage backend, lazily constructed at first
    call. Backend choice is fixed by `UPLOADS_BACKEND` env var (default
    `local`). Tests that need to swap mid-process can reset the
    module-level `_BACKEND` directly."""
    global _BACKEND
    if _BACKEND is None:
        choice = (os.environ.get("UPLOADS_BACKEND") or "local").strip().lower()
        if choice == "s3":
            _BACKEND = _S3Storage()
        else:
            _BACKEND = _LocalStorage()
    return _BACKEND


def reset_storage_for_test() -> None:
    """Force the next get_storage() call to re-read env vars and construct
    a fresh backend. Tests only — never call from app code."""
    global _BACKEND
    _BACKEND = None
