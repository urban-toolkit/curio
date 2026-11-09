"""A Hugging Face that the tests of the weights a model package's ``fetch`` names control.

Curio downloads those weights the first time a node runs the model
(``packages/infrastructure/fetched_weights.py``), through the transport seams a
pip install's left-out files use (``left_out_files.request_fn`` and
``resolver``). No test may open a socket (``tests/netguard.py``), so
``FakeHuggingFace`` stands in for both. As Hugging Face does, it answers
``GET https://huggingface.co/<repo>/resolve/<revision>/<path>`` with the file's
bytes, sends a big file through a redirect to another host, and refuses a
gated or gone repository with a status and an ``x-error-code``. It keeps every
request, with the headers and the timeout it was sent with.

The module under test is imported inside the functions that need it.
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote, unquote

HUGGING_FACE = "https://huggingface.co"
#: Where a big file is served from after the redirect, as Hugging Face's CDN.
CDN = "https://cdn.example-hf.co/xet-bridge"
#: An address both hosts resolve to: public, so the egress policy lets it through.
ADDRESS = "18.244.28.8"


def resolve_url(repository: str, revision: str, path: str) -> str:
    return f"{HUGGING_FACE}/{repository}/resolve/{revision}/{quote(path)}"


class FakeHuggingFace:
    """Serves *files* (``{path: bytes}``) of *repository* at *revision*.

    *redirect* names the paths served from :data:`CDN` after a 302. *status*,
    with *error_code*, refuses every file of the repository. *fail*, an
    exception, is raised instead of answering; *cut* sends the first half of
    a body, then raises it, as a dropped connection does. *before*, when
    given, is called with each URL before it is answered."""

    def __init__(self, repository: str, revision: str, files: dict, *, redirect=(), status=None,
                 error_code=None, fail=None, cut=None, before=None):
        self.prefix = f"{HUGGING_FACE}/{repository}/resolve/{revision}/"
        self.files = dict(files)
        self.redirect = set(redirect)
        self.status = status
        self.error_code = error_code
        self.fail = fail
        self.cut = cut
        self.before = before
        self.requests: list[SimpleNamespace] = []
        self.hosts: list[str] = []

    @property
    def urls(self) -> list[str]:
        return [request.url for request in self.requests]

    def resolver(self, host: str) -> list[str]:
        self.hosts.append(host)
        return [ADDRESS]

    def _body(self, body: bytes):
        half = len(body) // 2
        cut = self.cut

        def chunks():
            yield body[:half]
            if cut is not None:
                raise cut
            yield body[half:]

        return 200, {"Content-Length": str(len(body))}, None, chunks()

    def request(self, method, url, *, trusted_host=None, headers=None, timeout_s=None):
        self.requests.append(SimpleNamespace(method=method, url=url, headers=dict(headers or {}), timeout_s=timeout_s))
        if self.before is not None:
            self.before(url)
        if self.fail is not None:
            raise self.fail
        if method == "GET" and url.startswith(f"{CDN}/"):
            return self._body(self.files[unquote(url[len(CDN) + 1:])])
        if method != "GET" or not url.startswith(self.prefix):
            return 404, {"x-error-code": "RepoNotFound"}, None, iter([b'{"error":"Repository not found"}'])
        path = unquote(url[len(self.prefix):])
        if self.status is not None:
            answer = {"x-error-code": self.error_code} if self.error_code else {}
            return self.status, answer, None, iter([b'{"error":"refused"}'])
        if path not in self.files:
            return 404, {"x-error-code": "EntryNotFound"}, None, iter([b'{"error":"Entry not found"}'])
        if path in self.redirect:
            location = f"{CDN}/{quote(path)}"
            return 302, {"Location": location}, location, iter([])
        return self._body(self.files[path])

    def serve(self, monkeypatch) -> "FakeHuggingFace":
        """Make this the Hugging Face the code under test downloads from."""
        from utk_curio.backend.app.datasets.infrastructure import left_out_files

        monkeypatch.setattr(left_out_files, "request_fn", self.request)
        monkeypatch.setattr(left_out_files, "resolver", self.resolver)
        return self
