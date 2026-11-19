"""A Play the browser runs says how far its node's downloads on first use have come while it waits.

A hosted guest's Play, a shared viewer's and one with no project run in the
browser: the page posts ``/processPythonCode``, whose answer comes once the
node has run. A node's first run downloads what it reads first
(``execution/node_exec.py``), SAM 3's 3.4 GB of weights among them. While the
Play waits, the page asks ``GET /processPythonCode/progress?play=<id>``, with
the id it posted the Play with, how far those downloads have come, and shows
it on the node (``utils/nodeRunRequest.ts``), as a run on the server shows its
``step_progress``. Only the sign-in that posted the Play reads it.

The model package is the one ``test_model_catalog/test_fetched_weights.py``
makes, in this test's own folder; Hugging Face and the sandbox are fakes. The
Play runs on a thread of its own while the test asks, so the database is a
file (``conftest.py``). The code under test is imported inside each test.
"""
from __future__ import annotations

import threading

#: The id the page posts its Play with.
PLAY = "play-0a1b2c"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class _HeldHalfway:
    """Hugging Face's answers, with the body of *url* held once *half* of
    its bytes have come, until the test lets it go on: a download the page
    asks about while it is under way."""

    def __init__(self, hugging_face, url: str, half: int):
        self.hugging_face = hugging_face
        self.url = url
        self.half = half
        self.halfway = threading.Event()
        self.go_on = threading.Event()

    def request(self, method, url, **kwargs):
        status, headers, location, chunks = self.hugging_face.request(method, url, **kwargs)
        if url != self.url:
            return status, headers, location, chunks
        return status, headers, location, self._held(chunks)

    def _held(self, chunks):
        sent = 0
        for chunk in chunks:
            if sent >= self.half and not self.halfway.is_set():
                self.halfway.set()
                self.go_on.wait(30)
            sent += len(chunk)
            yield chunk


def test_a_play_says_how_far_its_nodes_weights_have_come_while_it_waits(
    app, client, user_and_token, guest_user_and_token, tmp_curio, monkeypatch,
):
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.tests._support.fetched_weights import CDN, FakeHuggingFace
    from utk_curio.backend.tests.test_model_catalog import test_fetched_weights as weights

    user, token = user_and_token
    _guest, guest_token = guest_user_and_token
    catalog = tmp_curio / "catalog"
    weights._write_package(catalog / weights.DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    weights._add(weights._key(user), catalog)
    hugging_face = FakeHuggingFace(
        weights.REPOSITORY, weights.REVISION, weights.FILES, redirect=("model.safetensors",), chunk_size=16,
    )
    held = _HeldHalfway(hugging_face, f"{CDN}/model.safetensors", len(weights.WEIGHTS) // 2)
    monkeypatch.setattr(left_out_files, "request_fn", held.request)
    monkeypatch.setattr(left_out_files, "resolver", hugging_face.resolver)
    sent = weights._capture_sandbox(monkeypatch)
    replies = []

    def play():
        replies.append(app.test_client().post("/processPythonCode", headers=_auth(token), json={
            "code": f'model = curio_load_model("{weights.PACKAGE_ID}")\nreturn 1',
            "nodeType": "PYTHON_COMPUTATION", "input": "", "progressId": PLAY,
        }))

    def ask(as_token):
        return client.get(f"/processPythonCode/progress?play={PLAY}", headers=_auth(as_token))

    playing = threading.Thread(target=play)
    playing.start()
    try:
        assert held.halfway.wait(30), "the Play's weights never began to download"
        asked = ask(token)
        assert asked.status_code == 200, (
            f"the page could not ask how far its Play's downloads had come: HTTP {asked.status_code}"
        )
        said = asked.get_json()
        assert "model.safetensors" in said["message"] and "%" in said["message"], said
        assert 0 < said["done"] < said["total"] == len(weights.WEIGHTS), said
        # Another sign-in reads nothing of it.
        assert ask(guest_token).get_json() == {"message": ""}
    finally:
        held.go_on.set()
        playing.join(30)

    assert not playing.is_alive()
    assert replies and replies[0].status_code == 200, replies and replies[0].get_data(as_text=True)
    assert len(sent) == 1, "the sandbox was not asked to run the node once its weights were here"
    # The Play over, there is nothing more to say of it.
    assert ask(token).get_json() == {"message": ""}
