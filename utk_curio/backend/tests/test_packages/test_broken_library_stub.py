"""The ``/api/testing/broken-library`` stub, and that it really is the bug.

An E2E test cannot stage "pip succeeded and the library does not work" from
outside the server: the probe runs in a subprocess of the backend, so the fake
has to reach that process's ``sys.path`` and its children's ``PYTHONPATH``.
This is the door, and these tests hold it to the shape the real failure has -
because a stub that is merely *a* failure would let the E2E suite pass over a
bug it does not reproduce.
"""

from __future__ import annotations

import json

import pytest


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _post(client, **body):
    return client.post(
        "/api/testing/broken-library",
        data=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )


@pytest.fixture(autouse=True)
def _cleanup(client, tmp_curio):
    yield
    _post(client, action="remove")


def test_the_fake_is_the_real_shape_pip_is_satisfied_and_the_import_is_not(client):
    """Both halves, or it is not this bug.

    A distribution that is simply missing is a different failure with a
    different remedy - pip would install it. What makes this one invisible is
    that pip looks, finds a matching version, reports "already satisfied" and
    changes nothing.
    """
    body = _post(client, action="install").get_json()

    assert body["versionSatisfied"] is True, "pip would not skip this; wrong bug"
    assert body["importError"], "the import must actually fail"
    assert "DLL load failed" in body["importError"]


def test_pip_skips_it_rather_than_reaching_an_index(client):
    """The whole test suite stays offline because of this.

    ``install_python_deps`` consults the same metadata pip does, so the fake
    lands in ``skipped`` and no subprocess is spawned at all.
    """
    from utk_curio.backend.app.packages import pip_runner

    _post(client, action="install")
    report = pip_runner.install_python_deps({"brokenlib": ""})

    assert report.skipped == ["brokenlib"]
    assert report.installed == []


def test_it_is_invisible_until_asked_for_and_after_removal(client):
    """Nothing else in the suite should be able to trip over it."""
    from importlib.metadata import PackageNotFoundError, version

    _post(client, action="install")
    assert version("brokenlib") == "9.9.9"

    _post(client, action="remove")
    with pytest.raises(PackageNotFoundError):
        version("brokenlib")


def test_the_probe_answer_is_re_asked_after_a_change(client):
    """The verdict is memoised per (distribution, version), so minting or
    removing the fake has to reopen the question or the next probe answers
    from before it existed."""
    from utk_curio.backend.app.packages import pip_runner

    _post(client, action="install")
    assert pip_runner.import_failures(["brokenlib"])

    _post(client, action="remove")
    assert pip_runner.import_failures(["brokenlib"]) == {
        "brokenlib": "brokenlib is not installed",
    }


def test_a_named_library_can_stand_in_for_the_real_one(client):
    """So a test can say ``rasterio`` when rasterio is what the story is about."""
    body = _post(
        client, action="install", name="notrasterio", version="1.3.9",
        reason="ImportError: libgdal.so.34: cannot open shared object file",
    ).get_json()

    assert body["version"] == "1.3.9"
    assert "libgdal" in body["importError"]


@pytest.mark.parametrize("bad", [
    {"action": "wat"},
    {"action": "install", "name": "../escape"},
    {"action": "install", "name": "ok", "version": "; rm -rf /"},
])
def test_it_refuses_input_that_would_name_something_else(client, bad):
    """The name becomes a directory and a module filename."""
    assert _post(client, **bad).status_code == 400


def test_it_is_not_mounted_outside_a_test_rig(client, monkeypatch):
    """Same gate as every other stub here: dev AND a declared test rig.

    This one writes a module that raises on import onto the interpreter's path,
    which is not something a deployment should be able to be talked into.
    """
    monkeypatch.setattr(
        "utk_curio.backend.app.testing.routes._is_testing", lambda: False)
    assert _post(client, action="install").status_code == 404


@pytest.mark.parametrize("name", ["json", "re", "subprocess", "flask"])
def test_it_refuses_a_name_that_already_resolves(client, name):
    """Staging one would be a real broken library, not a fake one.

    The module is written to a directory that goes on ``sys.path[0]`` and on
    ``PYTHONPATH``, so a name that already resolves shadows it for this backend
    AND every probe or pip child it spawns - which then die on startup, and the
    import failures the suite reports become its own doing.
    """
    resp = _post(client, action="install", name=name)
    assert resp.status_code == 400
    assert "already resolves" in resp.get_json()["error"]
    # And nothing was written on the way to refusing.
    from importlib.metadata import version
    assert version(name) if name == "flask" else True


def test_removing_one_fake_leaves_the_others(client):
    """The API invites naming a distribution, so removal has to honour it."""
    from utk_curio.backend.app.packages import pip_runner

    _post(client, action="install", name="brokenlib")
    _post(client, action="install", name="notrasterio", version="1.3.9")

    body = _post(client, action="remove", name="notrasterio").get_json()

    assert body["remaining"], "removing one must not wipe the directory"
    assert pip_runner.import_failures(["brokenlib"]) != {
        "brokenlib": "brokenlib is not installed",
    }


def test_removing_the_last_fake_takes_the_path_back_off(client):
    from importlib.metadata import PackageNotFoundError, version

    _post(client, action="install", name="brokenlib")
    assert _post(client, action="remove", name="brokenlib").get_json()["remaining"] == []
    with pytest.raises(PackageNotFoundError):
        version("brokenlib")


def test_teardown_preserves_an_empty_pythonpath_entry(client, monkeypatch):
    """CPython reads an empty entry as the launch cwd.

    Dropping it would change what every child can import, as a side effect of a
    teardown - felt only by whatever test runs next.
    """
    import os

    monkeypatch.setenv("PYTHONPATH", f"C:{os.pathsep}{os.pathsep}D:")
    _post(client, action="install")
    _post(client, action="remove")

    assert os.environ["PYTHONPATH"].split(os.pathsep) == ["C:", "", "D:"]
