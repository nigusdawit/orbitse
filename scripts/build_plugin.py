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

Publishing a new version
------------------------
1. Bump ``Version:`` in ``wordpress-plugin/ai-concierge.php`` (and ``AAP_VERSION``).
2. Run:  ``python scripts/build_plugin.py``
3. Deploy. Installed sites will see the WordPress "update available" button.

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


def read_version():
    """Pull the version from the plugin's ``Version:`` header."""
    with open(MAIN, encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"^\s*\*\s*Version:\s*([0-9][0-9A-Za-z.\-]*)", txt, re.MULTILINE)
    if not m:
        sys.exit("ERROR: Could not find a 'Version:' header in ai-concierge.php")
    return m.group(1)


def main():
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

    print(f"Built {zip_path} (v{version}) with {len(files)} file(s)")
    print(f"Wrote  {os.path.join(DIST, 'manifest.json')}")


if __name__ == "__main__":
    main()
