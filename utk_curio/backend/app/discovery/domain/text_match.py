"""Whether a typed search matches a row's text, and which matches come first.

Used wherever Curio filters rows itself rather than asking a portal to: a WFS
server's layer list, a storage or service source's declared resources, and the
source roster.

A search is a handful of words. A row matches when every word appears
somewhere in its text, in any order, as a whole word or inside a longer one.
Case and accents are ignored on both sides, so ``onibus`` finds "Pontos de
ônibus". A word of four letters or more ending in ``s`` also finds the word
without the ``s``, so ``distritos`` finds "Distrito". One of five or more
ending in ``es`` after r, s, z, x, ch or sh also finds the word without the
``es``, so ``flores`` finds "flor" and ``buses`` finds "bus". Irregular
plurals, such as ``-ões`` for ``-ão`` or ``-ais`` for ``-al``, are not
recognised.
"""

from __future__ import annotations

import unicodedata
from typing import Callable, Iterable, Sequence, TypeVar

Row = TypeVar("Row")

#: How a word ends when its plural adds ``es`` rather than ``s``: flor, luz,
#: país; bus, box, church, bush. Any other ``-es`` word is a ``-e`` word plus
#: ``s`` (redes, lines), whose stem without ``es`` would be a different word.
_ES_PLURAL_ENDINGS = ("r", "s", "z", "x", "ch", "sh")


def fold(text: str | None) -> str:
    """*text* without case or accents: ``"Ônibus"`` becomes ``"onibus"``."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def query_words(query: str | None) -> tuple[str, ...]:
    """The folded words of a search. No words means it matches every row."""
    return tuple(fold(query).split())


def _forms(word: str) -> tuple[str, ...]:
    """*word*, and the singulars it could be the plural of."""
    if len(word) < 4 or not word.endswith("s"):
        return (word,)
    stem = word[:-2]
    if len(word) >= 5 and word.endswith("es") and stem.endswith(_ES_PLURAL_ENDINGS):
        return (word, word[:-1], stem)
    return (word, word[:-1])


def has_word(folded_text: str, word: str) -> bool:
    """Whether *word*, or a singular of it, is in already folded text."""
    return any(form in folded_text for form in _forms(word))


def matches_folded(folded_text: str, words: Sequence[str]) -> bool:
    """Whether every one of *words* is in already folded text."""
    return all(has_word(folded_text, word) for word in words)


def matches(query: str | None, *texts: str | None) -> bool:
    """Whether every word of *query* is in one of *texts*."""
    words = query_words(query)
    if not words:
        return True
    return matches_folded(fold(" ".join(t for t in texts if t)), words)


def rank(
    rows: Iterable[Row],
    words: Sequence[str],
    *,
    head: Callable[[Row], str],
    name: Callable[[Row], str],
) -> list[Row]:
    """*rows*, best first: more of *words* in a row's folded *head* (its name
    and title) first, then the shorter *name*. Rows that tie keep their order,
    and with no words every row keeps its place."""
    rows = list(rows)
    if not words:
        return rows
    return sorted(
        rows,
        key=lambda row: (-sum(has_word(head(row), word) for word in words), len(name(row))),
    )
