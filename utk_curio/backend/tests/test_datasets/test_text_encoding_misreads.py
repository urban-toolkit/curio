"""Two ways an import read text wrongly without saying so.

* A file that is UTF-8 for most of its length and then holds a byte that is
  not was read in whichever single-byte codec fit that byte, so every accented
  letter before it came out as mojibake: ``São`` as ``SĂŁo``. It is refused,
  and says where UTF-8 stops.
* A short file in a single-byte codec, its accented letters standing alone
  between ASCII ones, was read by a two-byte codec: ``São Paulo`` as
  ``S緌 Paulo``. It is read one byte per character.

Both paths answer: ``to_utf8`` for bytes in memory and the streaming
``transcode_file_to_utf8`` for a file on disk.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.datasets.infrastructure.text_encoding import (
    UTF8_BOM,
    TextDecodeError,
    to_utf8,
    transcode_file_to_utf8,
)

#: Many accented letters, as UTF-8 writes them, before the byte that is not.
PORTUGUESE = "name,v\n" + "São Paulo,1\nMaceió,2\n" * 1500

#: Text whose bytes past ASCII sit side by side: two-byte letters, and Cyrillic.
RUNS_TOGETHER = [
    ("shift_jis", "名前,都市\n東京,日本\n大阪,日本\n"),
    ("gb18030", "名称,城市\n北京,中国\n上海,中国\n"),
    ("big5", "名稱,城市\n臺北,臺灣\n高雄,臺灣\n"),
    ("euc_kr", "이름,도시\n서울,한국\n부산,한국\n"),
    ("cp1251", "город,страна\nМосква,Россия\n"),
]


def streamed(tmp_path, data: bytes) -> tuple[bytes, str]:
    src, dest = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_bytes(data)
    encoding = transcode_file_to_utf8(src, dest, what="in.csv")
    return dest.read_bytes(), encoding


class TestUtf8TextWithAByteThatIsNot:
    @pytest.mark.parametrize("stray", [b"\xff", "é".encode("cp1252")], ids=["0xff", "a cp1252 accent"])
    def test_it_is_refused_rather_than_read_as_another_codec(self, tmp_path, stray):
        data = PORTUGUESE.encode("utf-8") + b"Rio" + stray + b",3\n"
        where = len(PORTUGUESE.encode("utf-8")) + len(b"Rio")
        with pytest.raises(TextDecodeError, match=f"is UTF-8 up to byte {where}"):
            to_utf8(data, what="in.csv")
        with pytest.raises(TextDecodeError, match=f"is UTF-8 up to byte {where}"):
            streamed(tmp_path, data)

    def test_a_byte_order_mark_alone_is_not_utf8_text(self, tmp_path):
        """Nothing but the mark says UTF-8, so the rest is read in its own
        encoding, and the mark is dropped rather than read as ``ï»¿``."""
        data = UTF8_BOM + "city\nCafé\n".encode("cp1252")
        for out, encoding in (to_utf8(data, what="in.csv"), streamed(tmp_path, data)):
            assert encoding == "cp1252"
            assert out.decode("utf-8") == "city\nCafé\n"

    def test_utf8_that_is_utf8_throughout_is_untouched(self, tmp_path):
        data = UTF8_BOM + PORTUGUESE.encode("utf-8")
        out, encoding = to_utf8(data, what="in.csv")
        assert encoding == "utf-8" and out is data
        assert streamed(tmp_path, data) == (data, "utf-8")


class TestAccentedLettersStandingAlone:
    @pytest.mark.parametrize(
        "text", ["name,v\nSão Paulo,2\n", "cidade\nMaceió\n", "a\nCafé\n", "city,note\nCafé,naïve\n"]
    )
    def test_a_short_single_byte_file_is_read_one_byte_per_character(self, tmp_path, text):
        data = text.encode("cp1252")
        for out, encoding in (to_utf8(data, what="in.csv"), streamed(tmp_path, data)):
            assert encoding == "cp1252"
            assert out.decode("utf-8") == text

    @pytest.mark.parametrize("codec, text", RUNS_TOGETHER, ids=[codec for codec, _ in RUNS_TOGETHER])
    def test_a_file_whose_letters_run_together_is_left_to_the_detector(self, codec, text):
        """The rule above is for bytes that stand alone. Where they sit side by
        side, as two-byte letters and Cyrillic words do, the answer is the
        detector's, as it was."""
        from charset_normalizer import from_bytes

        from utk_curio.backend.app.datasets.infrastructure import text_encoding

        data = text.encode(codec)
        ranked = [m for m in from_bytes(data) if m.encoding]
        assert text_encoding.detect_encoding(data) == text_encoding._pick(ranked)

    @pytest.mark.parametrize("codec, text", [c for c in RUNS_TOGETHER if c[0] != "big5"],
                             ids=[codec for codec, _ in RUNS_TOGETHER if codec != "big5"])
    def test_and_such_a_file_still_reads_right(self, tmp_path, codec, text):
        """Big5 is left out: charset-normalizer 3.5 reads this sample as cp932
        with or without the rule above, where 3.4 read it as Big5."""
        data = text.encode(codec)
        for out, _encoding in (to_utf8(data, what="in.csv"), streamed(tmp_path, data)):
            assert out.decode("utf-8") == text
