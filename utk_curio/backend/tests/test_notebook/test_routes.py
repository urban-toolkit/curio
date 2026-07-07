import json
import pytest
# from utk_curio.backend.app.notebooks import routes.py

def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def test_working(client):
    resp = client.get("api/alive")
    assert resp.status_code == 200
    assert resp.get_json() == {"response": 123}

def test_basic_llm_response(client, user_and_token, monkeypatch, db):
    user, token = user_and_token
    user.llm_model = "gpt-4o-mini"  # any non-empty string satisfies _resolve_llm_config
    db.session.commit()

    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._call_llm",
        lambda api_key, api_type, base_url, model, messages: "mocked response",
    )

    resp = client.post(
        "llm/chat",
        data=json.dumps({"preamble": "default_preamble", "prompt": "jupyter_notebook_prompt", "text": "Say something"}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["result"] == "mocked response"


# pytest utk_curio/backend/tests/test_notebook/test_routes.py