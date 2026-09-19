"""Detection samples a window; the decode covers the whole file (#368).

``detect_encoding`` reads at most ``SNIFF_BYTES`` because detection quality
plateaus and the cost is linear, but ``to_utf8`` then decodes everything. When
the window and the decode disagreed, two things went wrong, and both shipped:

* a file that is plain ASCII for its first 256 KiB and only turns non-ASCII
  after it was detected as ``ascii``; the whole-buffer decode then died on bytes
  detection had never looked at, and an upload that used to import returned 400;
* a BOM makes the detector answer ``utf_8`` whatever follows it, so the same
  file with a BOM took ``to_utf8``'s passthrough instead: HTTP 201, and the
  stored bytes were not valid UTF-8 at all. Silent corruption is the worse of
  the two, because everything downstream then fails on a file the import path
  promised was normalised.

These are unit tests on purpose. The boundary is a byte offset, so the whole
assertion is 262143 versus 262144 - the HTTP-level suite in
``test_csv_encoding_import.py`` proves the route, and its fixtures are 33 bytes,
four orders of magnitude inside the window.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.datasets.infrastructure.text_encoding import (
    SNIFF_BYTES,
    TextDecodeError,
    detect_encoding,
    to_utf8,
)


#: A byte that is valid cp1252/latin-1 ("é") and never a valid lone UTF-8 byte.
NON_ASCII = b"\xe9"


def _ascii_then_non_ascii(offset: int) -> bytes:
    """A buffer whose first non-ASCII byte sits exactly at *offset*."""
    return b"A" * offset + NON_ASCII + b",x\n"


@pytest.mark.parametrize(
    "offset",
    [
        SNIFF_BYTES - 1,  # inside the window: always worked
        SNIFF_BYTES,  # the exact boundary: this is what regressed
        SNIFF_BYTES + 1,
        SNIFF_BYTES * 4,  # far outside, to show it is not an off-by-one
    ],
)
def test_a_file_imports_whatever_the_offset_of_its_first_accent(offset):
    """The cutoff was the offset of the first non-ASCII byte, not file size.

    A 10 MB file with an accent at byte 5 always worked; a 300 KB file whose
    only accent sat at 262144 was refused. Nothing about the file's size or
    validity justified the difference, so it is the thing to pin.
    """
    data, encoding = to_utf8(_ascii_then_non_ascii(offset), what="cities.csv")

    assert encoding != "utf-8", "a single-byte codec should have been detected"
    data.decode("utf-8")  # raises if the stored bytes are not valid UTF-8


def test_a_bom_does_not_wave_bytes_through_unchecked():
    """The detector answers utf_8 for anything BOM'd; verify before trusting it.

    This one returned 201 and stored bytes that are not UTF-8 - the failure the
    whole normalise-on-import change exists to prevent, reintroduced by the one
    branch that skips the decode.
    """
    data, _ = to_utf8(
        b"\xef\xbb\xbf" + _ascii_then_non_ascii(SNIFF_BYTES * 2), what="bom.csv"
    )

    data.decode("utf-8")


def test_a_real_utf8_bom_is_still_passed_through_untouched():
    """The common path must not pay for the guard above."""
    original = "city,note\nCafé,naïve\n".encode("utf-8-sig")

    data, encoding = to_utf8(original, what="bom.csv")

    assert encoding == "utf-8"
    assert data is original, "already-UTF-8 input should copy nothing"


def test_detection_still_refuses_what_it_cannot_type():
    """Widening the window must not turn a refusal into a wrong guess.

    Not the reproducer it looks like: every byte of a run of control characters
    is valid ASCII, so ``utf-8`` is the right answer for one. A buffer spanning
    the whole byte range is what no codec can make words of.
    """
    junk = bytes(range(256)) * 4

    assert detect_encoding(junk) is None

    with pytest.raises(TextDecodeError):
        to_utf8(junk, what="junk.csv")
