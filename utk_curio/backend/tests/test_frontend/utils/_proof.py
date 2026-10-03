"""TMP PROOF, never merged: arms the real helpers inside the tests that patch them.

Armed only inside the two unit test files that patch ``utils.screenshots`` and
the probe file, so every other test sees the real helpers.
"""
import os

_PROOF_FILES = ("test_baseline_minting.py", "test_screenshot_comparison_records.py",
                "test_tmp_split_proof.py")


def proof_armed():
    return any(f in os.environ.get("PYTEST_CURRENT_TEST", "") for f in _PROOF_FILES)


def intercept(name):
    if proof_armed():
        raise RuntimeError(f"INTERCEPT PROOF: the real {name} ran inside a test")
