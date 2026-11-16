"""The tenant-isolation contract every workspace endpoint must satisfy.

To add a workspace endpoint, add it to ``WORKSPACE_ENDPOINTS``.
``test_architecture.py`` fails if a workspace route is missing from this
registry, and ``test_isolation.py`` runs every entry through the contract.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Endpoint:
    route: str  # exactly as it appears in the URL configuration
    method: str
    body: dict | None = None
    #: Statuses an authorised owner may get. Proves the URL is real, so the
    #: 404s asserted for outsiders are not vacuous.
    ok: tuple[int, ...] = (200,)
    id: str = field(default="", compare=False)


_BASE = "api/v1/workspaces/<uuid:workspace_id>/"

WORKSPACE_ENDPOINTS = [
    Endpoint(_BASE, "get"),
    Endpoint(_BASE + "members/", "get"),
    Endpoint(_BASE + "members/<uuid:membership_id>/", "patch", {"role": "attendant"}),
    Endpoint(_BASE + "devices/", "get"),
    Endpoint(_BASE + "devices/<uuid:device_id>/revoke/", "post"),
    Endpoint(_BASE + "devices/<uuid:device_id>/reauthorize/", "post"),
    Endpoint(_BASE + "sync/handshake/", "post"),
]


def build_url(route: str, workspace_id, **record_ids) -> str:
    url = "/" + route.replace("<uuid:workspace_id>", str(workspace_id))
    for name, value in record_ids.items():
        url = url.replace(f"<uuid:{name}>", str(value))
    assert "<" not in url, f"No sample id for a parameter in {route}"
    return url
