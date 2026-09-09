"""dev/116 — the ONE redactor every secret-carrying boundary calls."""

from utk_curio.backend.app.common.redaction import MIN_REDACT_CHARS, redact, redact_all


def test_values_are_replaced_by_name_longest_first():
    values = {"census": "abcdefgh1234", "inner": "abcdefgh"}
    text = "key=abcdefgh1234 and abcdefgh again"
    assert redact(text, values) == "key=«redacted:census» and «redacted:inner» again"


def test_short_values_none_and_empty_pass_through():
    assert redact("x" * 5, {"k": "x" * (MIN_REDACT_CHARS - 1)}) == "x" * 5
    assert redact(None, {"k": "abcdefgh"}) is None
    assert redact("keep me", {}) == "keep me"
    assert redact("keep me", None) == "keep me"
    assert redact(42, {"k": "abcdefgh"}) == 42  # non-text is returned untouched


def test_redact_all_maps_named_texts():
    out = redact_all({"stdout": "tok ZZZZZZZZZ", "stderr": None}, {"t": "ZZZZZZZZZ"})
    assert out == {"stdout": "tok «redacted:t»", "stderr": None}
