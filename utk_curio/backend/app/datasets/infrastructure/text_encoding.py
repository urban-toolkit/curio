"""Decide what a text upload's bytes actually are, and normalise them.

Curio's generated loader snippets carry no reader keyword arguments, by design:
``loader_snippet`` emits a bare ``pd.read_csv(dataset_path)`` and there is no
place to thread an ``encoding=`` through it. The catalog already lives with that
constraint elsewhere - its CSVs were re-saved comma-delimited on the way in
because the loader could not be told a delimiter either.

So the same answer applies to encoding (#280): decide once, at import, and store
UTF-8. Every reader downstream - the row counter, the preview, the generated
node code - can then assume UTF-8 and be right, instead of each one guessing.

``charset-normalizer`` does the detection. It arrives transitively with
``requests`` but is declared in ``requirements.txt`` in its own right, for the
reason given there about ``psutil`` and ``jsonschema``: a library that is
imported must be declared, or it quietly disappears the day the transitive does.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Bytes read to decide the encoding. Detection quality plateaus quickly and the
#: cost is linear, so this bounds a 2 GB upload's sniff to a fixed cost. The
#: decode itself still covers the whole file.
SNIFF_BYTES = 256 * 1024


class TextDecodeError(Exception):
    """The bytes could not be decoded as text under any candidate encoding."""


def detect_encoding(data: bytes) -> str | None:
    """Best guess at *data*'s encoding, or ``None`` if there is no good one.

    ``utf-8`` is answered directly rather than asked of the detector: it is the
    overwhelmingly common case, a strict decode is a definitive test, and the
    detector will sometimes prefer a single-byte codec that also happens to
    decode the sample.
    """
    if not data:
        return "utf-8"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes
    except ImportError:  # pragma: no cover - declared in requirements.txt
        logger.warning("charset-normalizer is unavailable; cannot detect encoding")
        return None

    matches = from_bytes(data[:SNIFF_BYTES])
    return _pick(matches)


#: Single-byte codecs that decode the same bytes to different letters cannot be
#: told apart by how *messy* the result looks - only by whether the words come
#: out meaning anything. When that is still a tie, this order decides. cp1252
#: first because it is what Windows and Excel emit across Western Europe and the
#: Americas, and is by a wide margin the most common encoding a CSV arrives in
#: that is not already UTF-8.
_PREFERRED = ("cp1252", "iso8859_1", "latin_1", "cp1251", "cp1250")

#: Two candidates whose chaos differs by less than this are treated as equally
#: plausible on mess alone, and decided on coherence instead.
_CHAOS_EPSILON = 0.01

#: And two whose coherence differs by less than this are treated as equally
#: meaningful, so ``_PREFERRED`` decides rather than noise. Measured on this
#: tree: for ordinary Western European CSV text the whole Latin-family group
#: ties to four decimal places, and the gaps that do appear between unrelated
#: codecs are an order of magnitude wider than this.
_COHERENCE_EPSILON = 0.05


def _pick(matches) -> str | None:
    """Choose among ranked candidates, preferring meaning over order.

    ``charset_normalizer``'s own ``best()`` sorts on chaos and, within a group
    that ties on it, returns whichever came first. For a Western European CSV
    that group is large and arbitrary: cp1250, cp1252, cp1257, iso8859_4 and
    iso8859_10 all decode the bytes without looking messy, and on the varied
    French/German sample measured here they tie on coherence to four decimals
    too. So the answer came down to enumeration order and landed on cp1250,
    which turns ``naïve`` into ``naďve``.

    So: take everything within ``_CHAOS_EPSILON`` of the least messy candidate,
    keep those within ``_COHERENCE_EPSILON`` of the most meaningful, and let
    ``_PREFERRED`` decide the rest. Mojibake that looks like data is worse than
    the crash this replaces, because nothing downstream can tell it is wrong.

    **This cannot be made reliable, only better.** Every single-byte codec
    decodes every byte, so there is no error to catch, and on degenerate input
    the detector prunes hard: for one line repeated 200 times it kept only
    cp775 and dropped cp1252 entirely. That is why the chosen encoding is
    written to the manifest as ``sourceEncoding`` and returned on the imported
    item - a wrong guess has to be visible and correctable, not silent.
    """
    ranked = [m for m in matches if m.encoding]
    if not ranked:
        return None
    floor = min(m.chaos for m in ranked)
    plausible = [m for m in ranked if m.chaos <= floor + _CHAOS_EPSILON]

    ceiling = max(m.coherence for m in plausible)
    coherent = [m for m in plausible if m.coherence >= ceiling - _COHERENCE_EPSILON]

    def preference(match):
        name = str(match.encoding).lower()
        return _PREFERRED.index(name) if name in _PREFERRED else len(_PREFERRED)

    return str(min(coherent, key=preference).encoding)


def to_utf8(data: bytes, *, what: str = "file") -> tuple[bytes, str]:
    """Return (*utf-8 bytes*, *source encoding*) for *data*.

    Already-UTF-8 input is returned unchanged and reported as ``utf-8``, so the
    common path copies nothing and the BOM, if any, is preserved exactly as
    uploaded. Raises :class:`TextDecodeError` when nothing decodes it, which is
    a refusal the caller can turn into a 400 rather than a dataset that breaks
    later.
    """
    encoding = detect_encoding(data)
    if encoding is None:
        raise TextDecodeError(
            f"Could not read {what} as text: its character encoding is not "
            "recognisable. Re-save it as UTF-8 and import it again."
        )
    if encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        return data, "utf-8"
    try:
        text = data.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise TextDecodeError(
            f"Could not read {what} as text: it looked like {encoding}, but "
            f"decoding it failed ({exc}). Re-save it as UTF-8 and import it again."
        ) from exc
    logger.info("Transcoded %s from %s to utf-8 on import", what, encoding)
    return text.encode("utf-8"), encoding


def open_text(path, **kwargs):
    """``path.open`` for a stored text file, tolerating a legacy encoding.

    Imports are normalised to UTF-8 (see :func:`to_utf8`), so the strict open is
    the answer for anything imported since. It is not the answer for everything
    on disk: datasets that predate that change, and files written by other paths,
    can still be cp1252 - and a preview that raises ``UnicodeDecodeError`` gives
    the user a 500 where a table would do.

    So: strict UTF-8 first, and only on failure pay for detection. ``utf-8-sig``
    because a BOM is preserved byte-for-byte by the import path and has to be
    stripped on read.
    """
    encoding = kwargs.pop("encoding", "utf-8-sig")
    try:
        handle = path.open("r", encoding=encoding, **kwargs)
        handle.read(SNIFF_BYTES)
        handle.seek(0)
        return handle
    except UnicodeDecodeError:
        handle.close()
    except Exception:
        raise

    detected = detect_encoding(path.read_bytes()[:SNIFF_BYTES])
    if detected is None:
        raise TextDecodeError(
            f"Could not read {path.name} as text: its character encoding is not "
            "recognisable."
        )
    logger.warning(
        "%s is not UTF-8; reading it as %s. Re-import it to normalise it.",
        path,
        detected,
    )
    return path.open("r", encoding=detected, **kwargs)
