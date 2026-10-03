"""The search rule Curio applies where it filters rows itself: a WFS server's
layer list, storage and service rows, and the source roster."""

from __future__ import annotations

import pytest


@pytest.fixture()
def tm():
    from utk_curio.backend.app.discovery.domain import text_match

    return text_match


class TestFold:
    def test_case_and_accents_are_dropped(self, tm):
        assert tm.fold("Pontos de Ônibus") == "pontos de onibus"
        assert tm.fold("São Paulo, Ação, Über, crème") == "sao paulo, acao, uber, creme"

    def test_nothing_folds_to_nothing(self, tm):
        assert tm.fold(None) == ""
        assert tm.query_words("   ") == ()


class TestMatches:
    def test_an_empty_search_matches_every_row(self, tm):
        assert tm.matches("", "anything")
        assert tm.matches("   ", "")
        assert tm.matches(None, None)

    def test_each_word_matches_on_its_own_in_any_order(self, tm):
        assert tm.matches("distrito municipal", "geoportal:distrito_municipal")
        assert tm.matches("municipal distrito", "geoportal:distrito_municipal")
        assert tm.matches("ponto onibus", "Pontos de ônibus")

    def test_every_word_has_to_be_found(self, tm):
        assert not tm.matches("ponto metro", "Pontos de ônibus")

    def test_a_word_may_be_part_of_a_longer_one(self, tm):
        assert tm.matches("ciclo", "geoportal:bicicletario_paraciclo")

    def test_accents_and_case_are_ignored_on_both_sides(self, tm):
        assert tm.matches("ônibus", "geoportal:ponto_onibus")
        assert tm.matches("onibus", "Pontos de ônibus")
        assert tm.matches("ACAO", "Ação social")

    def test_the_words_may_be_spread_over_the_texts_given(self, tm):
        assert tm.matches("distrito lei", "Distrito", None, "", "criados mediante a Lei")


class TestPlurals:
    @pytest.mark.parametrize(
        "query,text",
        [
            ("distritos", "Distrito"),
            ("pontos", "geoportal:ponto_onibus"),
            ("flores", "flor"),
            ("luzes", "luz"),
            ("países", "pais"),
            ("buses", "bus stop"),
            ("boxes", "box"),
            ("churches", "church"),
        ],
    )
    def test_a_plural_finds_its_singular(self, tm, query, text):
        assert tm.matches(query, text)

    def test_a_singular_finds_its_plural(self, tm):
        assert tm.matches("ponto", "Pontos de ônibus")

    @pytest.mark.parametrize(
        "query,text",
        [
            ("redes", "red line"),  # rede plus s: "red" is another word
            ("lines", "lin"),
            ("bus", "bu"),  # under four letters: no singular is tried
            ("gas", "ga"),
        ],
    )
    def test_only_a_plural_ending_is_taken_off(self, tm, query, text):
        assert not tm.matches(query, text)


def _rows(tm, *pairs):
    return [{"name": name, "head": tm.fold(f"{name} {title}")} for name, title in pairs]


def _ranked(tm, rows, query):
    return [
        r["name"]
        for r in tm.rank(rows, tm.query_words(query), head=lambda r: r["head"], name=lambda r: r["name"])
    ]


class TestRank:
    def test_more_words_in_the_name_or_title_come_first(self, tm):
        rows = _rows(
            tm,
            ("ws:abrigo", "Abrigos"),
            ("ws:linha_onibus", "Linhas"),
            ("ws:ponto_onibus", "Pontos de ônibus"),
        )
        assert _ranked(tm, rows, "ponto onibus") == ["ws:ponto_onibus", "ws:linha_onibus", "ws:abrigo"]

    def test_a_plural_word_counts_for_its_singular_in_the_name(self, tm):
        rows = _rows(tm, ("ws:zona", "Zonas"), ("ws:distrito_municipal", "Distrito"))
        assert _ranked(tm, rows, "distritos") == ["ws:distrito_municipal", "ws:zona"]

    def test_the_shorter_name_wins_a_tie(self, tm):
        rows = _rows(tm, ("ws:sac_remanejamento_ponto_onibus", ""), ("ws:ponto_onibus", ""))
        assert _ranked(tm, rows, "ponto onibus") == ["ws:ponto_onibus", "ws:sac_remanejamento_ponto_onibus"]

    def test_rows_that_tie_keep_their_order(self, tm):
        rows = _rows(tm, ("ws:faixa_onibus", ""), ("ws:linha_onibus", ""), ("ws:ponto_onibus", ""))
        assert _ranked(tm, rows, "onibus") == ["ws:faixa_onibus", "ws:linha_onibus", "ws:ponto_onibus"]
        assert _ranked(tm, rows[::-1], "onibus") == ["ws:ponto_onibus", "ws:linha_onibus", "ws:faixa_onibus"]

    def test_with_no_words_every_row_keeps_its_place(self, tm):
        rows = _rows(tm, ("ws:a_long_layer_name", ""), ("ws:a", ""))
        assert _ranked(tm, rows, "  ") == ["ws:a_long_layer_name", "ws:a"]
