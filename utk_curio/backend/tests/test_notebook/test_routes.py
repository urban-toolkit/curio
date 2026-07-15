import json
import pytest
# from utk_curio.backend.app.notebooks import routes.py

def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def test_auth_llm_response(client, user_and_token, monkeypatch, db):
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

def test_basic_llm_response(client, monkeypatch, user_and_token):
    user, token = user_and_token
    sample_input = [
        { "index": 1, "code": "import numpy as np\nimport matplotlib.pyplot as plt\n\nx = np.linspace(0, 10, 100)\ny = np.sin(x)\nprint(x[:5])"},
        { "index": 4, "code": "plt.plot(x, y)\nplt.title('Sine Wave')\nplt.xlabel('x')\nplt.ylabel('sin(x)')\nplt.show()"},
        { "index": 9, "code": "mean_y = np.mean(y)\nstd_y = np.std(y)\nprint(f\"Mean: {mean_y:.4f}, Std Dev: {std_y:.4f}\")"}
    ]

    resp = client.post(
        "api/llm/analysis",
        data = json.dumps({"cells": sample_input}, indent=2),
        headers = _auth(None) # {"Content-Type": "application/json"}
    )
    #_auth(token)

    result = resp.get_json()
    print(f"\n{result}\n")
    assert resp.status_code == 200


# pytest utk_curio/backend/tests/test_notebook/test_routes.py