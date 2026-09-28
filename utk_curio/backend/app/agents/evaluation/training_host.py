"""``host_of`` — a base URL reduced to what may be shown (dev/123).

Its own module because two services need it and neither should import the
other: the training service (dev/122) shows a destination host before an
upload, and the evaluation service shows which endpoint will answer. A base URL
can carry a key in a query string on some deployments, so only the network
location ever travels to a client.
"""

from __future__ import annotations

from urllib.parse import urlparse


def host_of(base_url: str, api_type: str = "") -> str:
    text = (base_url or "").strip()
    if text:
        parsed = urlparse(text if "//" in text else f"//{text}")
        if parsed.netloc:
            return parsed.netloc
    kind = (api_type or "").strip()
    return f"the default {kind} endpoint" if kind else ""
