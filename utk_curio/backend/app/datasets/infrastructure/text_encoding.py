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
import re
import unicodedata

logger = logging.getLogger(__name__)

UTF8_BOM = b"\xef\xbb\xbf"

#: A byte past ASCII, and two of them side by side.
_HIGH_BYTE = re.compile(rb"[\x80-\xff]")
_ADJACENT_HIGH_BYTES = re.compile(rb"[\x80-\xff]{2}")

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
    except UnicodeDecodeError as exc:
        first_bad = exc.start

    try:
        from charset_normalizer import from_bytes
    except ImportError:  # pragma: no cover - declared in requirements.txt
        logger.warning("charset-normalizer is unavailable; cannot detect encoding")
        return None

    # Anchored on the first byte that is not valid UTF-8, not on byte 0. A file
    # that is plain ASCII for its first SNIFF_BYTES and only turns non-ASCII
    # after it would otherwise be detected as "ascii", and to_utf8's
    # whole-buffer decode would then fail on bytes detection never looked at:
    # an upload that used to import now 400s (#368). The window stays the same
    # size, so the bounded cost this constant exists for is unchanged.
    start = max(0, first_bad - SNIFF_BYTES // 2)
    window = data[start:start + SNIFF_BYTES]
    matches = [m for m in from_bytes(window) if m.encoding]
    if matches and _ADJACENT_HIGH_BYTES.search(window) is None:
        return _one_byte_per_character(window, matches)
    return _pick(matches)


def _one_byte_per_character(window: bytes, matches) -> str:
    """The encoding for a sample whose bytes past ASCII each stand alone.

    That is how a single-byte codec writes an accented letter inside a word:
    ``S\xe3o Paulo``. A two-byte codec would pair each such byte with the ASCII
    one beside it, and on a short sample the detector can prefer that reading,
    or offer nothing else: for ``name,v\nS\xe3o Paulo,2\n`` it offered only
    Big5, GB18030, CP932 and Johab, and Big5 read ``S緌 Paulo``. So only the
    readings that keep one character per byte are candidates, and among them
    the ones that make a Latin letter of each such byte inside a word of ASCII
    letters: ``Caf\xe9`` is ``Café`` in cp1252 and ``Cafй`` in cp1251, and a
    word is not half Latin and half Cyrillic.

    When the detector recognised a language in one of them, it chooses, as it
    does for any sample. When it did not, which is the case for a short one,
    its ranking is noise (for ``city\nCaf\xe9\n`` it offered cp775 and
    mac_latin2 and not cp1252 at all), so the first of ``_PREFERRED`` that
    reads the sample so is the answer.
    """
    single = [m for m in matches if _decodes_one_char_per_byte(window, str(m.encoding))]
    latin = [m for m in single if _reads_latin_in_words(window, str(m.encoding))]
    pool = latin or single
    if any(m.coherence > 0 for m in pool):
        return _pick(pool) or str(pool[0].encoding)
    decodable = [name for name in _PREFERRED if _decodes_strictly(window, name)]
    fitting = [name for name in decodable if _reads_latin_in_words(window, name)]
    if fitting:
        return fitting[0]
    if pool:
        return _pick(pool) or str(pool[0].encoding)
    if decodable:
        return decodable[0]
    return _pick(matches) or str(matches[0].encoding)


def _decodes_strictly(window: bytes, encoding: str) -> bool:
    try:
        window.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return False
    return True


_ASCII_LETTERS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _reads_latin_in_words(window: bytes, encoding: str) -> bool:
    """Whether each byte past ASCII beside an ASCII letter reads as a Latin one."""
    seen: dict[int, bool] = {}
    for found in _HIGH_BYTE.finditer(window):
        at = found.start()
        before = window[at - 1] if at > 0 else None
        after = window[at + 1] if at + 1 < len(window) else None
        if before not in _ASCII_LETTERS and after not in _ASCII_LETTERS:
            continue
        value = window[at]
        if value not in seen:
            try:
                char = bytes([value]).decode(encoding)
            except (UnicodeDecodeError, LookupError):
                char = ""
            seen[value] = len(char) == 1 and unicodedata.name(char, "").startswith("LATIN")
        if not seen[value]:
            return False
    return True


def _decodes_one_char_per_byte(window: bytes, encoding: str) -> bool:
    try:
        return len(window.decode(encoding, errors="replace")) == len(window)
    except LookupError:
        return False


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


def _mixed_utf8(what: str, first_bad: int) -> TextDecodeError:
    return TextDecodeError(
        f"Could not read {what} as text: it is UTF-8 up to byte {first_bad}, and "
        "that byte is not. Re-save it as UTF-8 and import it again."
    )


def _detected(encoding: str | None, what: str, first_bad: int) -> str:
    """*encoding*, or the refusal for a file it cannot be."""
    if encoding is None:
        raise TextDecodeError(
            f"Could not read {what} as text: its character encoding is not "
            "recognisable. Re-save it as UTF-8 and import it again."
        )
    if encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        raise TextDecodeError(
            f"Could not read {what} as text: it looked like UTF-8, but byte "
            f"{first_bad} is not valid UTF-8. Re-save it as UTF-8 and import it again."
        )
    return encoding


def to_utf8(data: bytes, *, what: str = "file") -> tuple[bytes, str]:
    """Return (*utf-8 bytes*, *source encoding*) for *data*.

    Already-UTF-8 input is returned unchanged and reported as ``utf-8``, so the
    common path copies nothing and the BOM, if any, is preserved exactly as
    uploaded. Anything else is read in the encoding detected where its first
    byte that is not UTF-8 sits, with a leading BOM dropped: in any other
    encoding those three bytes are not text, and kept they head the first
    column's name as ``ï»¿``.

    Raises :class:`TextDecodeError`, a refusal the caller can turn into a 400
    rather than a dataset that breaks later, when nothing decodes it, and when
    it is UTF-8 text up to a byte that is not. Reading all of it in some other
    codec to fit that one byte would turn every character before it into
    mojibake, ``São`` into ``SĂŁo``, with nothing downstream able to tell.
    """
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        first_bad = exc.start
    else:
        return data, "utf-8"
    skip = len(UTF8_BOM) if data.startswith(UTF8_BOM) else 0
    # Everything before first_bad is valid UTF-8, so a byte past ASCII there
    # is part of a character UTF-8 wrote.
    if _HIGH_BYTE.search(data, skip, first_bad) is not None:
        raise _mixed_utf8(what, first_bad)
    body = data[skip:] if skip else data
    encoding = _detected(detect_encoding(body), what, first_bad)
    try:
        text = body.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise TextDecodeError(
            f"Could not read {what} as text: it looked like {encoding}, but "
            f"decoding it failed ({exc}). Re-save it as UTF-8 and import it again."
        ) from exc
    logger.info("Transcoded %s from %s to utf-8 on import", what, encoding)
    return text.encode("utf-8"), encoding


#: Chunk size for the streaming transcode. Memory stays at a few of these.
STREAM_CHUNK_BYTES = 1024 * 1024


def _first_invalid_utf8(path) -> int | None:
    """Offset of the first byte that is not valid UTF-8, or None if all are."""
    import codecs

    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    offset = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(STREAM_CHUNK_BYTES)
            try:
                decoder.decode(chunk, final=not chunk)
            except UnicodeDecodeError as exc:
                # ``exc.start`` indexes the buffer the decoder held: its pending
                # bytes plus this chunk. Pending bytes are at most three.
                pending = len(decoder.getstate()[0]) if hasattr(decoder, "getstate") else 0
                return max(0, offset - pending + exc.start)
            if not chunk:
                return None
            offset += len(chunk)


def _high_byte_between(path, start: int, end: int) -> bool:
    """Whether *path* holds a byte past ASCII from *start* up to *end*."""
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = end - start
        while remaining > 0:
            chunk = handle.read(min(STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                return False
            if _HIGH_BYTE.search(chunk) is not None:
                return True
            remaining -= len(chunk)
    return False


def transcode_file_to_utf8(src, dest, *, what: str = "file") -> str:
    """Write *src* to *dest* as UTF-8 and return the encoding it was read as.

    The file-sized sibling of :func:`to_utf8`, with the same answers: UTF-8
    input is copied byte for byte (a BOM included), anything else is decoded
    with the detected encoding (a leading BOM dropped) and re-encoded, and
    :class:`TextDecodeError` is raised when nothing decodes it or it is UTF-8
    text up to a byte that is not. Detection reads the window
    :func:`to_utf8`'s would, anchored on the first byte that is not UTF-8, so
    the whole file never has to be in memory.
    """
    import codecs
    import shutil
    from pathlib import Path

    src, dest = Path(src), Path(dest)
    first_bad = _first_invalid_utf8(src)
    if first_bad is None:
        shutil.copyfile(src, dest)
        return "utf-8"
    with open(src, "rb") as handle:
        skip = len(UTF8_BOM) if handle.read(len(UTF8_BOM)) == UTF8_BOM else 0
    if _high_byte_between(src, skip, first_bad):
        raise _mixed_utf8(what, first_bad)

    start = skip + max(0, first_bad - skip - SNIFF_BYTES // 2)
    with open(src, "rb") as handle:
        handle.seek(start)
        window = handle.read(SNIFF_BYTES)
    encoding = _detected(detect_encoding(window), what, first_bad)
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    except LookupError as exc:
        raise TextDecodeError(f"Could not read {what} as text: unknown encoding {encoding}") from exc
    try:
        with open(src, "rb") as reader, open(dest, "wb") as writer:
            reader.seek(skip)
            while True:
                chunk = reader.read(STREAM_CHUNK_BYTES)
                writer.write(decoder.decode(chunk, final=not chunk).encode("utf-8"))
                if not chunk:
                    break
    except UnicodeDecodeError as exc:
        dest.unlink(missing_ok=True)
        raise TextDecodeError(
            f"Could not read {what} as text: it looked like {encoding}, but "
            f"decoding it failed ({exc}). Re-save it as UTF-8 and import it again."
        ) from exc
    logger.info("Transcoded %s from %s to utf-8 on import", what, encoding)
    return encoding


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
        # The whole file, not the first SNIFF_BYTES: the caller reads to EOF, so
        # validating a prefix only moved the UnicodeDecodeError into the caller
        # as an uncaught 500 for a legacy file whose first non-ASCII byte sits
        # past the window. Chunked, so a large file costs time and not memory.
        while handle.read(SNIFF_BYTES):
            pass
        handle.seek(0)
        return handle
    except UnicodeDecodeError:
        handle.close()
    except Exception:
        raise

    # Whole file: detect_encoding does its own bounded, anchored sampling, and
    # slicing here would hide the very bytes that made the strict open fail.
    detected = detect_encoding(path.read_bytes())
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
