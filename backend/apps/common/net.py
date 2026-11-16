"""The client's network address, as far as it can be trusted.

Only ``TRUSTED_PROXY_COUNT`` reverse proxies in front of the application are
believed. Each trusted proxy appends the address it received the request from
to ``X-Forwarded-For``, so with N trusted proxies the client is the N-th entry
from the right. Anything further left was written by the client and is
ignored. With no trusted proxy the header is ignored entirely.
"""

import ipaddress

from django.conf import settings


def client_ip(request) -> str:
    """The best trustworthy address for ``request`` (a Django ``HttpRequest``)."""
    remote = request.META.get("REMOTE_ADDR", "")
    trusted = settings.TRUSTED_PROXY_COUNT
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if trusted <= 0 or not forwarded:
        return _clean(remote)
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if len(hops) < trusted:
        # Fewer hops than trusted proxies: the chain is not what we expect,
        # so fall back to the address of the peer we actually talk to.
        return _clean(remote)
    return _clean(hops[-trusted])


def address_bucket(ip: str) -> str:
    """The unit an address is limited by: the address itself for IPv4, its
    /64 network for IPv6 (one subscriber usually holds a whole /64)."""
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    if parsed.version == 6:
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


def _clean(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return "unknown"
