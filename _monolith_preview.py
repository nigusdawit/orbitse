"""TEMP preview launcher — boots the MONOLITH (app.py) against an embedded
Postgres, seeds a test embed key + an enabled chatbot + a sample gallery card,
and ALSO serves embed-test.html from a SECOND origin (port 8099) so you can load
the widget cross-origin in a real browser. Delete after use.

Run:
  uv run --python 3.12 --with pgserver --with flask --with flask-compress \
    --with psycopg2-binary --with openai --with anthropic --with stripe \
    --with requests --with httpx --with brotli --with rjsmin --with cryptography \
    --with pillow --with "sentry-sdk[flask]" --with boto3 --with pymupdf \
    --with pypdf --with python-docx --with python-pptx python _monolith_preview.py

Then open:  http://127.0.0.1:8099/embed-test.html
(Set OPENAI_API_KEY in the environment first if you want live chat replies; the
widget will still MOUNT and open without a key — only the reply needs one.)
"""
import http.server
import os
import socketserver
import tempfile
import threading

MONOLITH_PORT = 5056
TESTPAGE_PORT = 8099


def _serve_test_page():
    here = os.path.dirname(os.path.abspath(__file__))

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=here, **k)

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", TESTPAGE_PORT), Handler) as httpd:
        print(f"[preview] test page: http://127.0.0.1:{TESTPAGE_PORT}/embed-test.html", flush=True)
        httpd.serve_forever()


def main():
    import pgserver
    data_dir = tempfile.mkdtemp(prefix="monolith_preview_")
    srv = pgserver.get_server(data_dir)
    os.environ["DATABASE_URL"] = srv.get_uri()
    os.environ.setdefault("FLASK_SECRET_KEY", "preview-secret-stable")
    os.environ.setdefault("ADMIN_PASSWORD", "admin")
    print(f"[preview] embedded PG: {srv.get_uri()}", flush=True)

    import app as monolith
    try:
        monolith.init_db()
    except Exception as e:
        print(f"[preview] init_db note: {e}", flush=True)

    # Seed: a wildcard test embed key, an enabled chatbot, a sample gallery card.
    monolith.execute_db("DELETE FROM tenant_embed_keys WHERE embed_key='pk_preview'")
    monolith.execute_db(
        "INSERT INTO tenant_embed_keys (tenant_id, embed_key, label, origin_allowlist) "
        "VALUES (1,'pk_preview','preview','[\"*\"]'::jsonb)")
    try:
        monolith.execute_db("UPDATE chatbot_settings SET enabled=TRUE, greeting='Hi! Ask me anything.' WHERE id=1")
    except Exception as e:
        print(f"[preview] chatbot enable note: {e}", flush=True)
    try:
        monolith.execute_db(
            "INSERT INTO gallery_cards (slug, title, subtitle, image_url, category) "
            "VALUES ('welcome','Welcome','A sample card','', 'spaces') "
            "ON CONFLICT (slug) DO NOTHING")
    except Exception as e:
        print(f"[preview] gallery seed note: {e}", flush=True)

    threading.Thread(target=_serve_test_page, daemon=True).start()

    print(f"[preview] monolith: http://127.0.0.1:{MONOLITH_PORT}  (embed key: pk_preview)", flush=True)
    print(f"[preview] >>> OPEN: http://127.0.0.1:{TESTPAGE_PORT}/embed-test.html <<<", flush=True)
    monolith.app.run(host="127.0.0.1", port=MONOLITH_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
