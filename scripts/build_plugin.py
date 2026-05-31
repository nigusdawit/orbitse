#!/usr/bin/env python3
"""Package the WordPress plugin into plugin_dist/ for self-hosted auto-updates.

What it does
------------
1. Reads the ``Version:`` header from ``wordpress-plugin/ai-concierge.php``.
2. Zips the plugin into ``plugin_dist/ai-concierge.zip`` with a top-level
   ``ai-concierge/`` folder (WordPress requires the zip to contain that folder so
   it installs/updates into ``wp-content/plugins/ai-concierge/``).
3. Writes ``plugin_dist/manifest.json`` — the file the platform serves at
   ``/plugin/update.json`` so every installed plugin knows the latest version.

It can be used two ways:

* From the command line (publishing a new version by hand)::

      python scripts/build_plugin.py              # rebuild at current version
      python scripts/build_plugin.py 1.2.0        # bump to 1.2.0, then build

* As a library (the admin "WP Plugin" tab imports ``bump_version`` + ``build``).

No external dependencies — pure standard library.
"""

import datetime
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "wordpress-plugin")
DIST = os.path.join(ROOT, "plugin_dist")
SLUG = "ai-concierge"
MAIN = os.path.join(SRC, "ai-concierge.php")
README = os.path.join(SRC, "readme.txt")

# A normal semantic-ish version: digits/letters/dots/hyphens, must start with a digit.
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.\-]{0,29}$")


def read_version():
    """Pull the version from the plugin's ``Version:`` header."""
    with open(MAIN, encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"^\s*\*\s*Version:\s*([0-9][0-9A-Za-z.\-]*)", txt, re.MULTILINE)
    if not m:
        raise ValueError("Could not find a 'Version:' header in ai-concierge.php")
    return m.group(1)


def is_valid_version(v):
    return bool(VERSION_RE.match((v or "").strip()))


def bump_version(new_version):
    """Rewrite the version in the plugin source so the next build publishes it.

    Updates three places that must stay in lockstep:
      * the ``Version:`` plugin header (what WordPress reads),
      * the ``AAP_VERSION`` PHP constant (what the plugin compares against), and
      * the ``Stable tag`` line in readme.txt.

    Returns ``(old_version, new_version)``. Raises ValueError on a bad version
    or a non-increasing bump (WordPress only offers an update when the manifest
    version is strictly greater than what's installed).
    """
    new_version = (new_version or "").strip()
    if not is_valid_version(new_version):
        raise ValueError("Invalid version. Use digits, dots and hyphens, e.g. 1.2.0")
    old_version = read_version()
    if _version_tuple(new_version) <= _version_tuple(old_version):
        raise ValueError(
            f"New version ({new_version}) must be greater than current ({old_version})."
        )

    with open(MAIN, encoding="utf-8") as f:
        php = f.read()
    php, n1 = re.subn(
        r"(^\s*\*\s*Version:\s*)([0-9][0-9A-Za-z.\-]*)",
        lambda m: m.group(1) + new_version, php, count=1, flags=re.MULTILINE)
    php, n2 = re.subn(
        r"(define\('AAP_VERSION',\s*')([0-9][0-9A-Za-z.\-]*)('\))",
        lambda m: m.group(1) + new_version + m.group(3), php, count=1)
    if not n1 or not n2:
        raise ValueError("Could not rewrite the Version header / AAP_VERSION constant.")
    with open(MAIN, "w", encoding="utf-8") as f:
        f.write(php)

    # readme.txt Stable tag (best-effort — don't fail the whole bump if absent).
    try:
        with open(README, encoding="utf-8") as f:
            rd = f.read()
        rd, _ = re.subn(r"(?im)^(Stable tag:\s*)([0-9][0-9A-Za-z.\-]*)\s*$",
                        lambda m: m.group(1) + new_version, rd, count=1)
        with open(README, "w", encoding="utf-8") as f:
            f.write(rd)
    except FileNotFoundError:
        pass

    return old_version, new_version


def _version_tuple(v):
    """Loose version compare key. Numeric chunks compare numerically, anything
    else (rc/beta suffixes) falls back to string so we never crash on odd input."""
    parts = []
    for chunk in re.split(r"[.\-]", v or ""):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
    return parts


def build():
    """Zip the plugin + write the manifest. Returns a small summary dict."""
    version = read_version()
    os.makedirs(DIST, exist_ok=True)

    # Bundle every file in wordpress-plugin/ under a top-level SLUG/ folder.
    zip_name = f"{SLUG}.zip"
    zip_path = os.path.join(DIST, zip_name)
    files = sorted(
        f for f in os.listdir(SRC) if os.path.isfile(os.path.join(SRC, f))
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in files:
            z.write(os.path.join(SRC, fn), arcname=f"{SLUG}/{fn}")

    # The platform overrides download_url at serve time (per request host), so we
    # only need version + metadata here.
    manifest = {
        "name": "AI Concierge",
        "slug": SLUG,
        "version": version,
        "zip": zip_name,
        "requires": "5.8",
        "tested": "6.5",
        "requires_php": "7.4",
        "last_updated": datetime.date.today().isoformat(),
        "description": "Hosted AI Concierge widget + embedded admin for WordPress.",
        "changelog": "See your platform release notes.",
    }
    with open(os.path.join(DIST, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    return {"version": version, "zip": zip_name, "zip_path": zip_path,
            "file_count": len(files), "files": files}


def main():
    if len(sys.argv) > 1:
        old, new = bump_version(sys.argv[1])
        print(f"Bumped version {old} -> {new}")
    info = build()
    print(f"Built {info['zip_path']} (v{info['version']}) with {info['file_count']} file(s)")
    print(f"Wrote  {os.path.join(DIST, 'manifest.json')}")


if __name__ == "__main__":
    main()
