"""
VELO Client — outbound calls from this Flask app to the VELO Master AI.

VELO Master is a separate FastAPI service (typically running on
http://localhost:8000 in dev) that brokers tools and routes commands
between this client install and any other connected agents.

Usage:
    from velo_client import velo

    # Discover what tools VELO currently exposes
    tools = velo.discover()

    # Use one of them
    result = velo.use_tool("admin_ai", "web_search", {"query": "..."})

    # Or report an event VELO may auto-handle
    velo.report_event("visitor_ai", "escalation",
                     {"question": "...", "session_id": "..."})

If VELO_MASTER_URL is not set, calls raise RuntimeError so callers can
gracefully degrade. If VELO_AGENT_KEY is empty, requests still go out
unauthenticated (master may accept this in dev mode).
"""

import os
import requests

VELO_URL = os.environ.get("VELO_MASTER_URL", "").strip()
VELO_AGENT_KEY = os.environ.get("VELO_AGENT_KEY", "").strip()


class VeloClient:
    """Dynamic HTTP client for talking to the VELO Master AI gateway."""

    def __init__(self):
        self.base_url = VELO_URL
        self.headers = {
            "Authorization": f"Bearer {VELO_AGENT_KEY}",
            "Content-Type": "application/json",
        }
        self._capabilities = None

    def _require_url(self):
        if not self.base_url:
            raise RuntimeError(
                "VELO_MASTER_URL is not set; cannot call VELO Master."
            )

    def discover(self):
        """Fetch VELO's current capability list. Cached on the instance."""
        self._require_url()
        resp = requests.get(
            f"{self.base_url}/api/capabilities",
            headers=self.headers,
            timeout=10,
        )
        resp.raise_for_status()
        self._capabilities = resp.json().get("capabilities", [])
        return self._capabilities

    def use_tool(self, agent_id, tool_name, tool_input):
        """Call any VELO tool dynamically.

        agent_id   — which local agent is making the call (e.g. "admin_ai")
        tool_name  — one of the names returned by discover()
        tool_input — must match that tool's input_schema
        """
        self._require_url()
        resp = requests.post(
            f"{self.base_url}/api/agent-gateway",
            headers=self.headers,
            json={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def report_event(self, agent_id, event_type, data):
        """Tell VELO an event happened. VELO may auto-handle it."""
        self._require_url()
        resp = requests.post(
            f"{self.base_url}/api/agent-gateway",
            headers=self.headers,
            json={
                "agent_id": agent_id,
                "tool_name": "report_event",
                "tool_input": {"event_type": event_type, "data": data},
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


velo = VeloClient()
