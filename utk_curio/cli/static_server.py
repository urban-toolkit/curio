"""The static server for the built frontend, with deep links and dashboard pages."""

import json
import os
import re
import urllib.error
import urllib.request

from html import escape as html_escape
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from utk_curio.common.backend_address import backend_base_url


# How long the page server waits for the backend to assemble a dashboard before
# serving the page without its data. Generous because assembling reads every
# artifact behind a tile, and mean because a visitor is sitting on a blank tab:
# past this the page loads and fetches for itself, which is what it did before.
DASHBOARD_EMBED_TIMEOUT = 30

# How ``GET /api/projects/<id>/dashboard`` refuses to build a dashboard as a page
# of its own: 413, its data is over the page's size limit; 409, a pinned tile
# loads its own data. The page then carries the backend's reason instead of the
# data (``_refused_page``), shows it, and fetches nothing.
DASHBOARD_REFUSALS = (409, 413)

# ``/dashboard/<uuid>`` is the only route whose HTML carries data. Matched here
# rather than "any path under /dashboard" so a typo serves an ordinary page
# instead of asking the backend about a project id that cannot exist.
DASHBOARD_PATH_RE = re.compile(
    r"^/dashboard/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/?$"
)


def _refused_page(project_id: str, answer: urllib.error.HTTPError) -> dict:
    """What the page of a dashboard the backend refused carries instead of its
    data: the backend's reason, in its own words (it names the nodes or tiles
    to change), and the dataflow's name for the page's bar.

    Read as ``src/standalone/dashboardPayload.ts`` reads a payload: ``meta``,
    and ``refused`` in place of the spec and the rows.
    """
    try:
        body = json.loads(answer.read().decode("utf-8"))
    except Exception:
        body = None
    body = body if isinstance(body, dict) else {}
    reason = body.get("error")
    name = body.get("name")
    return {
        "meta": {"projectId": project_id, "name": name if isinstance(name, str) else None},
        "refused": {
            "status": answer.code,
            "message": reason if isinstance(reason, str) and reason
            else f"The server would not build this dashboard (HTTP {answer.code}).",
        },
    }


def _payload_backend(backend_url: str) -> str:
    """Where this server asks for a dashboard's data, given ``--backend-url``.

    An http(s) address is asked as a browser would ask it. A path, such as the
    hosted stacks' ``/api``, is on whichever host serves the page, where a
    proxy hands it to the backend with the prefix stripped; this server sits
    behind that proxy, so it asks the backend the launcher started, at the
    address the launcher hands its children (``backend_base_url``), as the
    sandbox does. No ``--backend-url``, no data.
    """
    if not backend_url:
        return ""
    if backend_url.startswith(("http://", "https://")):
        return backend_url.rstrip("/")
    return backend_base_url()


def run_spa_static_server(directory: str, port: int, base_path: str = "", backend_url: str = "") -> None:
    """Serve a built SPA with index.html fallback for deep links.

    ``python -m http.server`` returns 404 for routes like ``/auth/signup`` or
    ``/workflow/<id>`` because those files do not exist on disk. Our frontend
    is a client-side router, so non-asset GETs should fall back to
    ``index.html`` instead.

    The page is written for the instance serving it, so one build serves any:
    *base_path* (``--base-path``, such as ``/app``) becomes its ``<base>``,
    which the bundle loads its assets relative to and the router reads its
    basename from, and *backend_url* (``--backend-url``) goes into a
    ``<meta name="curio-backend-url">`` that ``backendUrl.ts`` reads. A request
    that still carries the prefix, because no proxy in front strips it, is
    served too.

    A dashboard's page is served with its data, which this server asks the
    backend for itself (``_payload_backend``).
    """

    dist_dir = os.path.abspath(directory)
    index_file = os.path.join(dist_dir, "index.html")
    base_tag = f'<base href="{base_path}/">'
    backend_tag = f'<meta name="curio-backend-url" content="{html_escape(backend_url)}">' if backend_url else ""
    payload_backend = _payload_backend(backend_url)

    def index_html(extra_head: str = "") -> bytes:
        with open(index_file, encoding="utf-8") as fh:
            html = fh.read()
        if base_path or backend_tag or extra_head:
            tags = base_tag + backend_tag + extra_head
            # Replacement FUNCTION, not a replacement string: `re.sub` expands
            # escapes in a string replacement, and an embedded payload is full
            # of `<`. As a string this raises "bad escape \u" from inside
            # the request handler, which the browser sees as the connection
            # dropping on a page that was working a moment ago.
            html, found = re.subn(r"<base\b[^>]*>", lambda m: tags, html, count=1)
            if not found:
                html, found = re.subn(r"<head\b[^>]*>", lambda m: m.group(0) + tags, html, count=1)
            if not found:
                html = tags + html
        return html.encode("utf-8")

    def dashboard_payload_tag(project_id: str) -> str:
        """A dashboard's spec and rows, or why it has none, inlined so the page
        fetches nothing.

        The whole point of the page is that it stands on its own, so the
        fetching happens here, once, on the server, instead of a dozen times in
        the browser. This process has no database, so it asks the backend for
        the assembled payload, at ``payload_backend``.

        A dashboard the backend refuses to build (``DASHBOARD_REFUSALS``)
        carries the backend's reason in its place, and the page says why and
        fetches nothing: a page that fetched its rows itself would look
        standalone and not be. Any other failure, the backend down, failing or
        slower than ``DASHBOARD_EMBED_TIMEOUT``, returns "", which leaves an
        ordinary SPA page that fetches for itself.
        """
        if not payload_backend:
            return ""
        try:
            with urllib.request.urlopen(
                f"{payload_backend}/api/projects/{project_id}/dashboard",
                timeout=DASHBOARD_EMBED_TIMEOUT,
            ) as resp:
                if resp.status != 200:
                    return ""
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as answer:
            if answer.code not in DASHBOARD_REFUSALS:
                return ""
            payload = json.dumps(_refused_page(project_id, answer))
        except Exception:
            return ""
        # `</script>` anywhere inside the JSON would close this tag early, and
        # the rest of the payload would be parsed as markup. JSON escapes of the
        # same characters mean the identical value to JSON.parse.
        safe = (
            payload.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029")
        )
        return f'<script id="curio-dashboard-payload" type="application/json">{safe}</script>'

    class SpaStaticHandler(SimpleHTTPRequestHandler):
        # The 1.0 default closes the socket after every response, so one page
        # load opens hundreds of connections. Safe: every response here carries
        # a Content-Length.
        protocol_version = "HTTP/1.1"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dist_dir, **kwargs)

        def _serves_index(self) -> bool:
            """Drop the base path from ``self.path``; True when the answer is index.html."""
            path, sep, query = self.path.partition("?")
            path = path.split("#", 1)[0]
            if base_path and (path == base_path or path.startswith(base_path + "/")):
                path = path[len(base_path):] or "/"
                self.path = path + sep + query
            if path in ("", "/", "/index.html"):
                return True
            # Fall back on what the client asked for, not on whether the path
            # looks like it has a file extension. ``splitext`` reads a dotted
            # dataset id - ``data.utk.acs-neighborhood-profile`` - as the
            # extension ``.acs-neighborhood-profile``, so an extension test
            # refuses exactly the deep links this fallback exists to serve. A
            # browser navigation sends ``Accept: text/html``; a missing bundle
            # fetched with ``Accept: */*`` still gets its 404.
            accepts_html = "text/html" in (self.headers.get("Accept") or "")
            return accepts_html and not os.path.exists(os.path.join(dist_dir, path.lstrip("/")))

        def _send_index(self, with_body: bool) -> None:
            # Only a real navigation gets the payload. A HEAD, or any other
            # probe, would pay the assembly cost for a body nobody reads.
            extra = ""
            if with_body:
                path = self.path.partition("?")[0].split("#", 1)[0]
                match = DASHBOARD_PATH_RE.match(path)
                if match:
                    extra = dashboard_payload_tag(match.group(1))
            body = index_html(extra)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if with_body:
                self.wfile.write(body)

        def do_GET(self):
            if self._serves_index():
                return self._send_index(with_body=True)
            return super().do_GET()

        def do_HEAD(self):
            if self._serves_index():
                return self._send_index(with_body=False)
            return super().do_HEAD()

    with ThreadingHTTPServer(("0.0.0.0", port), SpaStaticHandler) as httpd:
        httpd.serve_forever()
