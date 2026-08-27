"""The out-of-process door to the scripted LLM provider.

``/api/testing/agent-script`` exists so an E2E test driving a separate
``curio.py start`` subprocess can script an agent turn and read back what
reached the model. Everything it does in-process is already covered by
``test_testing_provider.py``; what is only true at the route is the wire shape
and, above all, the guards.

Those guards carry real weight. Unlike ``stub-login``, these routes read prompt
text *back out* of the process, so they must not exist on an ordinary developer
dev server - only under ``CURIO_TESTING``.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import testing_provider


SCRIPT_URL = "/api/testing/agent-script"


@pytest.fixture(autouse=True)
def _testing_enabled(monkeypatch):
    """The routes 404 unless the scripted provider is available at all."""
    monkeypatch.setattr(testing_provider, "enabled", lambda: True)
    testing_provider.reset()
    yield
    testing_provider.reset()


class TestGuards:
    def test_404_when_not_a_test_run(self, client, monkeypatch):
        """The claim that matters: a dev server without CURIO_TESTING has no
        prompt-readback surface, even though the blueprint is registered."""
        monkeypatch.setattr(testing_provider, "enabled", lambda: False)
        assert client.get(SCRIPT_URL).status_code == 404
        assert client.post(SCRIPT_URL, json={"replies": []}).status_code == 404
        assert client.delete(SCRIPT_URL).status_code == 404

    def test_404_outside_dev(self, client, monkeypatch):
        """The blueprint-level production guard still applies on top."""
        monkeypatch.setattr(
            "utk_curio.backend.app.testing.routes._is_dev", lambda: False
        )
        assert client.get(SCRIPT_URL).status_code == 404
        assert client.post(SCRIPT_URL, json={"replies": []}).status_code == 404

    def test_no_auth_is_required(self, client):
        """Deliberate: the E2E fixture scripts a reply before it has a user, and
        the guards above are what keep the route safe, not a token."""
        assert client.post(SCRIPT_URL, json={"replies": ["hi"]}).status_code == 200


class TestPush:
    def test_replies_are_queued_in_order(self, client):
        resp = client.post(SCRIPT_URL, json={"replies": ["first", "second"]})
        assert resp.status_code == 200
        assert resp.get_json()["pending"] == 2
        assert testing_provider.run_scripted_completion([]) == "first"
        assert testing_provider.run_scripted_completion([]) == "second"

    def test_reset_is_the_default(self, client):
        """A reply left over from a previous test would be consumed by the next
        one, and the failure would point anywhere but at the cause."""
        testing_provider.push_reply("stale")
        assert client.post(SCRIPT_URL, json={"replies": ["fresh"]}).get_json()[
            "pending"
        ] == 1
        assert testing_provider.run_scripted_completion([]) == "fresh"

    def test_reset_false_appends(self, client):
        client.post(SCRIPT_URL, json={"replies": ["first"]})
        resp = client.post(SCRIPT_URL, json={"replies": ["second"], "reset": False})
        assert resp.get_json()["pending"] == 2

    def test_an_empty_body_just_resets(self, client):
        testing_provider.push_reply("stale")
        assert client.post(SCRIPT_URL, json={}).get_json()["pending"] == 0

    def test_non_string_replies_are_refused(self, client):
        resp = client.post(SCRIPT_URL, json={"replies": ["ok", 7]})
        assert resp.status_code == 400
        assert "list of strings" in resp.get_json()["error"]

    def test_a_non_list_is_refused(self, client):
        assert client.post(SCRIPT_URL, json={"replies": "oops"}).status_code == 400

    def test_a_refused_body_does_not_disturb_the_queue(self, client):
        client.post(SCRIPT_URL, json={"replies": ["keep me"]})
        client.post(SCRIPT_URL, json={"replies": [None]})
        assert testing_provider.pending() == 1
        assert testing_provider.run_scripted_completion([]) == "keep me"


class TestRead:
    def test_captured_prompts_come_back(self, client):
        testing_provider.run_scripted_completion(
            [{"role": "system", "content": "an agent instruction"},
             {"role": "user", "content": "hello"}]
        )
        body = client.get(SCRIPT_URL).get_json()
        assert body["pending"] == 0
        assert len(body["captured"]) == 1
        assert body["captured"][0][0]["content"] == "an agent instruction"

    def test_rounds_stay_separate(self, client):
        """A multi-round run has to be legible as rounds - that is how a test
        tells a tool follow-up apart from the opening turn."""
        testing_provider.run_scripted_completion([{"role": "user", "content": "a"}])
        testing_provider.run_scripted_completion([{"role": "user", "content": "b"}])
        captured = client.get(SCRIPT_URL).get_json()["captured"]
        assert [c[0]["content"] for c in captured] == ["a", "b"]

    def test_nothing_captured_reads_as_empty(self, client):
        assert client.get(SCRIPT_URL).get_json() == {"pending": 0, "captured": []}


class TestReset:
    def test_delete_clears_queue_and_capture(self, client):
        client.post(SCRIPT_URL, json={"replies": ["queued"]})
        testing_provider.run_scripted_completion([{"role": "user", "content": "x"}])
        assert client.delete(SCRIPT_URL).get_json() == {"pending": 0}
        body = client.get(SCRIPT_URL).get_json()
        assert body == {"pending": 0, "captured": []}
