"""Task 102 (gap §4.1) — per-page "Views · 7d". Embedded Postgres (no mocks).

The Pages list shows a 7-day public view count per page. page_views are logged by raw
URL ('/p/<slug>?...'); the endpoint strips the query string with split_part and
EXACT-matches the path against '/p/'||slug, so prefix collisions (/p/about vs
/p/about-us) never bleed into each other.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def _mk_page(slug, title=""):
    return app.execute_db(
        "INSERT INTO pages (slug, title) VALUES (%s, %s) "
        "ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title RETURNING id",
        (slug, title or slug),
    )["id"]


def _view(page_url, days_ago=0):
    app.execute_db(
        "INSERT INTO page_views (session_id, page_url, created_at) "
        "VALUES (%s, %s, NOW() - MAKE_INTERVAL(days => %s))",
        ("wp-test", page_url, days_ago),
    )


def test_page_view_counts_7d_exact_match_and_window():
    about = _mk_page("wp-about")
    aboutus = _mk_page("wp-about-us")
    try:
        _view("/p/wp-about", 0)                 # recent
        _view("/p/wp-about?utm_source=fb", 1)   # recent, query string stripped
        _view("/p/wp-about", 30)                # OLD — outside the 7d window
        _view("/p/wp-about-us", 2)              # prefix-collision page, recent
        j = _sa().get("/admin/api/page-view-counts?days=7").get_json()
        assert j["days"] == 7
        views = j["views"]
        # wp-about: the 2 recent views only — the 30-day-old one is excluded and the
        # wp-about-us view does NOT bleed in (exact path match, not a LIKE prefix).
        assert views[str(about)] == 2
        # wp-about-us: exactly its own single view.
        assert views[str(aboutus)] == 1
    finally:
        app.execute_db("DELETE FROM page_views WHERE session_id = 'wp-test'")
        app.execute_db("DELETE FROM pages WHERE slug IN ('wp-about', 'wp-about-us')")


def test_page_view_counts_requires_admin():
    # unauthenticated must not get a 200 (admin_required blocks/redirects)
    assert app.app.test_client().get("/admin/api/page-view-counts").status_code != 200


def test_page_view_counts_shape_and_clamp():
    c = _sa()
    j = c.get("/admin/api/page-view-counts?days=3").get_json()
    assert j["days"] == 3 and isinstance(j["views"], dict)
    # garbage days → falls back to 7; out-of-range is clamped (>365 → 365)
    assert c.get("/admin/api/page-view-counts?days=abc").get_json()["days"] == 7
    assert c.get("/admin/api/page-view-counts?days=99999").get_json()["days"] == 365
