"""Tests for the VELO master ↔ client communication surface.

Pins the fixes for the April 28 incident where VELO Master reported
"no tools discovered" + 405 errors when trying to use this client's
admin_ai agent. Three root causes traced from the velo_audit_log:

  1. Master probes for capabilities by sending command="" or
     command="list" / "tools" / "capabilities" etc. The handler
     was returning 400 "unknown command" for all of them — even
     though we have 30+ registered handlers.
  2. GET /api/velo/command (master probing for connectivity) was
     falling through to the homepage catch-all and returning HTML 200,
     which the master parses as garbage.
  3. POST /api/velo/admin_ai (master auto-derives per-agent URLs)
     was hitting the GET-only homepage catch-all and returning 405.

Each class below corresponds to one of those fix points.
"""

import json
import pytest


# Aliases the master might send to discover capabilities. Mirrors
# velo_endpoints._DISCOVERY_ALIASES — kept in sync by an explicit
# test (test_alias_set_matches_module_constant) below.
DISCOVERY_PROBE_COMMANDS = [
    "", "list", "list_commands", "list_tools", "tools",
    "discover", "discovery", "capabilities", "help",
    "describe", "?", "ls", "show",
    # Case variants — the handler lowercases before lookup
    "LIST", "Tools", "Capabilities", "  list  ",
]


class TestDiscoveryProbes:
    """Discovery aliases on POST /api/velo/command. The audit log
    proved the master sends command='' and command='list' as discovery
    probes; without these aliases registered, the master sees the
    standard 'unknown command' 400 and reports 'no tools discovered'."""

    @pytest.mark.parametrize("probe", DISCOVERY_PROBE_COMMANDS)
    def test_probe_returns_tools_list_with_200(self, client, velo_auth_headers, probe):
        resp = client.post(
            "/api/velo/command",
            json={"command": probe, "params": {}}, headers=velo_auth_headers)
        assert resp.status_code == 200, (
            f"discovery probe command={probe!r} got {resp.status_code} "
            f"body={resp.get_data(as_text=True)[:200]} — master would "
            f"surface this as 'no tools discovered'"
        )
        body = resp.get_json()
        assert body["status"] == "ok"
        result = body["result"]
        assert "commands" in result
        assert "total" in result
        assert result["total"] == len(result["commands"])
        assert result["total"] > 0, (
            "discovery probe returned an empty tools list — that's the "
            "exact failure the master reports as 'no tools discovered'"
        )

    def test_probe_includes_canonical_endpoint_urls(self, client, velo_auth_headers):
        resp = client.post("/api/velo/command", json={"command": "list"}, headers=velo_auth_headers)
        result = resp.get_json()["result"]
        for key in ("command_endpoint", "chat_endpoint",
                    "status_endpoint", "tools_endpoint"):
            assert key in result, f"discovery payload missing {key}"
            assert result[key].endswith(f"/api/velo/{key.replace('_endpoint','').replace('_','-')}") \
                or result[key].endswith(f"/api/velo/{key.replace('_endpoint','')}"), (
                f"{key} URL doesn't look right: {result[key]}"
            )

    def test_probe_includes_agent_ids(self, client, velo_auth_headers):
        # Master needs to know which agent_ids it can address. Without
        # this in the discovery payload, master has to guess and gets
        # 'unknown command' for unknown agent names.
        resp = client.post("/api/velo/command", json={"command": ""}, headers=velo_auth_headers)
        result = resp.get_json()["result"]
        assert set(result["agent_ids"]) == {"admin_ai", "visitor_ai"}

    def test_probe_includes_usage_hints(self, client, velo_auth_headers):
        resp = client.post("/api/velo/command", json={"command": "tools"}, headers=velo_auth_headers)
        result = resp.get_json()["result"]
        usage = result.get("usage", {})
        for key in ("structured_command", "free_text_chat", "discovery"):
            assert key in usage, f"usage hints missing {key}"
            assert "/api/velo/" in usage[key], (
                f"usage hint for {key} doesn't reference any /api/velo/ URL"
            )

    def test_alias_set_matches_module_constant(self):
        # Pin that the test list above matches the actual module
        # constant — drift here means a probe the master sends won't
        # be recognised even though tests pass.
        from velo_endpoints import _DISCOVERY_ALIASES
        # Test list normalised the same way the handler does
        normalised_test_aliases = {p.strip().lower() for p in DISCOVERY_PROBE_COMMANDS}
        # Every test alias must be in the module constant (after normalisation)
        missing = normalised_test_aliases - set(_DISCOVERY_ALIASES)
        assert not missing, (
            f"test list has aliases not in module constant: {missing}"
        )


class TestUnknownCommandHint:
    """The 400 response for an actually-unknown command must include
    enough hints for the master to self-correct on the next call."""

    def test_unknown_command_returns_400_with_chat_hint(self, client, velo_auth_headers):
        resp = client.post(
            "/api/velo/command",
            json={"command": "nonexistent_made_up_command_xyz", "params": {}}, headers=velo_auth_headers)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "hint" in body
        assert "/api/velo/chat" in body["hint"]
        assert "agent_id" in body["hint"]
        assert "chat_endpoint" in body
        assert body["chat_endpoint"].endswith("/api/velo/chat")
        assert "command_endpoint" in body
        assert "available_commands" in body
        assert isinstance(body["available_commands"], list)

    def test_unknown_command_when_master_treats_agent_as_command(self, client, velo_auth_headers):
        # Common master mistake: sending {"command": "admin_ai"} thinking
        # admin_ai is a callable command. The hint should make clear this
        # is a chat scenario, not a command scenario.
        resp = client.post(
            "/api/velo/command",
            json={"command": "admin_ai", "params": {"message": "hi"}}, headers=velo_auth_headers)
        assert resp.status_code == 400
        body = resp.get_json()
        assert "/api/velo/chat" in body["hint"]


class TestDiscoveryByGet:
    """GET /api/velo/tools and /capabilities for masters using the
    OpenAPI/MCP convention. Also GET /command for those probing
    connectivity. All return the same canonical discovery payload."""

    @pytest.mark.parametrize("path", [
        "/api/velo/tools",
        "/api/velo/capabilities",
        "/api/velo/command",
    ])
    def test_get_returns_discovery_payload(self, client, velo_auth_headers, path):
        resp = client.get(path, headers=velo_auth_headers)
        assert resp.status_code == 200, (
            f"GET {path} returned {resp.status_code} — master probing "
            f"this URL would conclude there are no tools here"
        )
        body = resp.get_json()
        assert body is not None, (
            f"GET {path} returned non-JSON (probably HTML from the "
            f"homepage catch-all) — master can't parse this"
        )
        assert body["status"] == "ok"
        assert "commands" in body["result"]
        assert body["result"]["total"] > 0

    def test_get_chat_returns_usage_hint_not_405(self, client, velo_auth_headers):
        # GET /chat used to return 405 (POST-only) → master surfaced
        # "405 — that command isn't supported that way". Now it
        # returns a usage hint with the body schema.
        resp = client.get("/api/velo/chat", headers=velo_auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["method"] == "POST"
        assert "body_schema" in body
        assert "message" in body["body_schema"]
        assert "agent_id" in body["body_schema"]

    def test_all_discovery_surfaces_return_same_command_list(self, client, velo_auth_headers):
        # Drift between discovery surfaces is a silent failure: master
        # sees tool X on one endpoint but not another, gets confused
        # about whether X exists. Pin that they all return the same
        # commands list.
        get_tools = client.get("/api/velo/tools", headers=velo_auth_headers).get_json()["result"]
        get_caps = client.get("/api/velo/capabilities", headers=velo_auth_headers).get_json()["result"]
        get_cmd = client.get("/api/velo/command", headers=velo_auth_headers).get_json()["result"]
        post_probe = client.post(
            "/api/velo/command", json={"command": "list"}, headers=velo_auth_headers).get_json()["result"]

        cmd_names = lambda r: sorted(c["name"] for c in r["commands"])
        all_lists = [cmd_names(r) for r in (get_tools, get_caps, get_cmd, post_probe)]
        assert all(lst == all_lists[0] for lst in all_lists), (
            f"discovery surfaces disagree about command list: {all_lists}"
        )


class TestVeloUnmatchedRoutes:
    """Wildcard /api/velo/<path:rest> for unrecognised paths. Without
    this, GET /api/velo/admin_ai serves the homepage HTML and POST
    returns 405 from the homepage catch-all — the literal failure
    a real master operator saw on April 28."""

    @pytest.mark.parametrize("path,method", [
        ("/api/velo/admin_ai", "GET"),
        ("/api/velo/admin_ai", "POST"),
        ("/api/velo/visitor_ai", "POST"),
        ("/api/velo/admin_ai/anything", "POST"),
        ("/api/velo/totally-made-up", "GET"),
        ("/api/velo/totally-made-up", "POST"),
        ("/api/velo/admin_ai/web_search", "POST"),  # per-agent per-tool URL
    ])
    def test_unknown_velo_path_returns_404_json_with_endpoint_map(
        self, client, velo_auth_headers, path, method
    ):
        resp = client.open(path, method=method, json={}, headers=velo_auth_headers)
        # Status must be 404 (NOT 200 with HTML, NOT 405)
        assert resp.status_code == 404, (
            f"{method} {path} returned {resp.status_code} — without the "
            f"wildcard catch-all, master sees HTML 200 or a 405 here"
        )
        body = resp.get_json()
        assert body is not None, (
            f"{method} {path} returned non-JSON — master can't parse this"
        )
        assert "endpoints" in body
        endpoints = body["endpoints"]
        # Every canonical endpoint must be listed with method + url
        for name in ("tools", "capabilities", "status",
                     "command", "chat", "refresh_registration"):
            assert name in endpoints, f"endpoint map missing {name}"
            assert "method" in endpoints[name]
            assert "url" in endpoints[name]
            assert endpoints[name]["url"].endswith(f"/api/velo/{name.replace('_','-')}") \
                or endpoints[name]["url"].endswith(f"/api/velo/{name}")
        assert body["agent_ids"] == ["admin_ai", "visitor_ai"]

    def test_known_routes_still_win_over_wildcard(self, client, velo_auth_headers):
        # Routing precedence sanity check: the wildcard must NOT
        # shadow the actual /command endpoint. If it did, the real
        # POST /command flow would route to velo_unmatched and every
        # capability call would 404.
        resp = client.post(
            "/api/velo/command",
            json={"command": "list"}, headers=velo_auth_headers)
        assert resp.status_code == 200, (
            "wildcard catch-all is shadowing /command — routing is broken"
        )

    def test_status_route_unaffected_by_wildcard(self, client, velo_auth_headers):
        resp = client.get("/api/velo/status", headers=velo_auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert "available_commands" in body
        assert body["status"] == "ok"

    @pytest.mark.parametrize("path,method", [
        ("/api/velo/command", "PUT"),
        ("/api/velo/command", "PATCH"),
        ("/api/velo/command", "DELETE"),
        ("/api/velo/status", "POST"),
        ("/api/velo/status", "DELETE"),
        ("/api/velo/tools", "DELETE"),
        ("/api/velo/chat", "PATCH"),
    ])
    def test_unsupported_method_on_known_path_resolves_to_wildcard_404(
        self, client, velo_auth_headers, path, method
    ):
        # Architect-flagged routing semantic: because the wildcard
        # accepts every method, an unsupported method on a known path
        # (e.g. PUT /command, POST /status) resolves to the wildcard
        # 404 with endpoint map INSTEAD of Flask's stock 405.
        #
        # This is intentional and master-friendly: a wrong-method probe
        # gets a self-describing JSON response listing every endpoint
        # with its allowed method, so the master can self-correct on
        # the next call. A 405 by itself carries no hint about which
        # method IS allowed and forces the master into another guessing
        # round. Pinning this so a future "let's restore HTTP-spec 405
        # behaviour" refactor surfaces as a deliberate test change
        # rather than a silent semantic flip.
        resp = client.open(path, method=method, json={}, headers=velo_auth_headers)
        assert resp.status_code == 404
        body = resp.get_json()
        assert "endpoints" in body, (
            f"{method} {path}: expected wildcard 404 JSON with endpoint "
            f"map, got {body!r}"
        )

    def test_agent_ids_constant_used_consistently(self, client, velo_auth_headers):
        # Drift guard: agent_ids appears in 3 response bodies (discovery
        # payload, GET /chat hint, wildcard 404). Every one must come
        # from the AGENT_IDS module constant, not a hardcoded literal,
        # so adding a third agent in one place doesn't silently leave
        # the other two stale. The architect specifically called out
        # this duplication risk.
        from velo_endpoints import AGENT_IDS
        expected = list(AGENT_IDS)

        # 1. Discovery payload (POST /command list)
        d = client.post("/api/velo/command", json={"command": "list"},
                        headers=velo_auth_headers).get_json()["result"]
        assert d["agent_ids"] == expected

        # 2. GET /chat hint
        c = client.get("/api/velo/chat", headers=velo_auth_headers).get_json()
        assert c["agent_ids"] == expected

        # 3. Wildcard 404 response
        w = client.get("/api/velo/some_random_unknown_path",
                       headers=velo_auth_headers).get_json()
        assert w["agent_ids"] == expected

    def test_wildcard_does_not_require_auth(self, client, velo_auth_headers, monkeypatch):
        # Even with auth required (production), the wildcard 404 hint
        # must work — it's a routing self-description and carries no
        # secrets. A master that hasn't authed yet still needs to
        # know what URLs exist so it can authenticate against them.
        import velo_endpoints
        monkeypatch.setattr(velo_endpoints, "VELO_AGENT_KEY", "test-key-required")
        # No Authorization header sent
        resp = client.post("/api/velo/some_random_path", json={}, headers=velo_auth_headers)
        assert resp.status_code == 404
        body = resp.get_json()
        assert "endpoints" in body


class TestProductionRegression:
    """Direct replays of the audit-log entries that originally surfaced
    the bug. If any of these regress, the April 28 failure is back."""

    def test_audit_log_regression_empty_command(self, client, velo_auth_headers):
        # 2026-04-27 18:32:36  cmd=''  err='unknown command'
        resp = client.post("/api/velo/command", json={"command": ""}, headers=velo_auth_headers)
        assert resp.status_code == 200, (
            "REGRESSION: empty-command probe is back to returning 4xx, "
            "master will report 'no tools discovered' again"
        )

    def test_audit_log_regression_list_command(self, client, velo_auth_headers):
        # 2026-04-27 19:08:38  cmd='list'  err='unknown command'
        resp = client.post("/api/velo/command", json={"command": "list"}, headers=velo_auth_headers)
        assert resp.status_code == 200, (
            "REGRESSION: command='list' probe is back to returning 4xx"
        )

    def test_audit_log_regression_post_to_admin_ai_path(self, client, velo_auth_headers):
        # The literal 405 the master operator surfaced. Must now be a
        # structured 404 JSON, not a 405 from the homepage catch-all.
        resp = client.post("/api/velo/admin_ai", json={}, headers=velo_auth_headers)
        assert resp.status_code == 404, (
            f"REGRESSION: POST /api/velo/admin_ai returned "
            f"{resp.status_code} (expected 404 JSON from velo wildcard) "
            f"— master will surface the original 405 message again"
        )
        body = resp.get_json()
        assert "endpoints" in body
