"""TMP PROOF, never merged: each helper the unit tests patch, called for real.

Every test here is expected to FAIL with "INTERCEPT PROOF: the real <name>
ran". That shows the raise on this branch is armed in the module that now
defines each helper, that ``screenshots``' name for it is the same armed
function, and that the package's re-export is too. The tests that patch these
names on ``screenshots`` pass only because each patch replaces the name where it
is looked up.
"""
import pytest

from utk_curio.backend.tests.test_frontend import utils
from utk_curio.backend.tests.test_frontend.utils import capture_waits, images, screenshots

DEFINED_IN = {
    "_capture_full_page": images,
    "_capture_element": images,
    "_volatile_boxes": screenshots,
    "_wait_for_no_node_running": capture_waits,
    "_wait_for_reactflow_ready": capture_waits,
    "dismiss_toasts": capture_waits,
}
ARGS = {
    "_capture_full_page": (object(),),
    "_capture_element": (object(), "#x"),
    "_volatile_boxes": (object(), None),
    "_wait_for_no_node_running": (object(),),
    "_wait_for_reactflow_ready": (object(),),
    "dismiss_toasts": (object(),),
}


@pytest.mark.parametrize("name", sorted(ARGS))
def test_the_real_helper_is_armed(name):
    getattr(DEFINED_IN[name], name)(*ARGS[name])


@pytest.mark.parametrize("name", sorted(n for n in ARGS if DEFINED_IN[n] is not screenshots))
def test_the_screenshots_name_is_the_same_armed_helper(name):
    assert getattr(screenshots, name) is getattr(DEFINED_IN[name], name)
    getattr(screenshots, name)(*ARGS[name])


@pytest.mark.parametrize("name", ["_wait_for_no_node_running", "_wait_for_reactflow_ready", "dismiss_toasts"])
def test_the_package_name_is_the_same_armed_helper(name):
    assert getattr(utils, name) is getattr(DEFINED_IN[name], name)
    getattr(utils, name)(*ARGS[name])
