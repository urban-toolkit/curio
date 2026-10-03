"""Place search for the area field: OpenStreetMap's geocoder, used politely."""
from __future__ import annotations

import threading

import pytest

from utk_curio.backend.app.discovery.application import places
from utk_curio.backend.app.discovery.domain.errors import ProviderError


@pytest.fixture(autouse=True)
def _fresh():
    places.reset()
    yield
    places.reset()


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


class _Counting:
    """A transport that answers one recorded place and counts its requests."""

    def __init__(self, answer=None):
        self.urls: list[str] = []
        self.headers: list[dict] = []
        self.answer = answer if answer is not None else [{
            "name": "Loop", "display_name": "Loop, Chicago, Cook County, Illinois, United States",
            "category": "boundary", "type": "administrative", "osm_type": "relation",
            "boundingbox": ["41.8673", "41.8906", "-87.6382", "-87.6025"],
        }]

    def json_get(self, url, *, credential=None, headers=None):
        self.urls.append(url)
        self.headers.append(dict(headers or {}))
        return self.answer


class _Nominatim(_Counting):
    """Answers Cologne as Nominatim does: ``name`` and ``display_name`` in the
    request's language, English here, and the place's own OpenStreetMap names
    only when the URL asks for ``namedetails``."""

    def __init__(self):
        super().__init__(answer=[{
            "name": "Cologne", "display_name": "Cologne, North Rhine-Westphalia, Germany",
            "category": "boundary", "type": "administrative", "osm_type": "relation",
            "boundingbox": ["50.8304399", "51.0849743", "6.7725303", "7.1620280"],
        }])

    def json_get(self, url, *, credential=None, headers=None):
        [place] = super().json_get(url, credential=credential, headers=headers)
        if "namedetails=1" in url.partition("?")[2].split("&"):
            place = {**place, "namedetails": {"name": "Köln", "name:de": "Köln", "name:en": "Cologne"}}
        return [place]


class TestTheSearch:
    def test_a_place_comes_back_as_a_box_and_its_osm_name(self):
        [loop] = places.search_places(_Counting(), "Loop, Chicago")
        assert loop["name"] == "Loop"
        assert loop["box"] == [-87.6382, 41.8673, -87.6025, 41.8906]
        assert loop["boundary"] is True
        assert loop["label"].startswith("Loop, Chicago")

    def test_a_place_is_named_as_openstreetmap_names_it_and_labelled_in_english(self):
        """A named area is matched against the boundary's OpenStreetMap
        ``name``, which is the local one: Köln, not Cologne."""
        [cologne] = places.search_places(_Nominatim(), "Cologne")
        assert cologne["name"] == "Köln"
        assert cologne["label"] == "Cologne, North Rhine-Westphalia, Germany"

    def test_it_names_itself_as_nominatim_asks(self):
        transport = _Counting()
        places.search_places(transport, "Loop")
        assert transport.headers[0]["User-Agent"] == places.USER_AGENT

    def test_a_repeated_search_is_answered_without_a_request(self):
        transport = _Counting()
        places.search_places(transport, "Loop, Chicago")
        places.search_places(transport, "  loop,   chicago ")
        assert len(transport.urls) == 1

    def test_two_searches_are_a_second_apart(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(places.time, "sleep", lambda s: slept.append(s))
        transport = _Counting()
        places.search_places(transport, "Loop")
        places.search_places(transport, "Near North Side")
        assert len(transport.urls) == 2
        assert slept and 0 < slept[-1] <= places.MIN_INTERVAL_S

    def test_two_searches_at_once_still_leave_a_second_apart(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr(places.time, "sleep", lambda s: slept.append(s))
        transport = _Counting()
        together = threading.Barrier(2)

        def search(query):
            together.wait(timeout=10)
            places.search_places(transport, query)

        searches = [threading.Thread(target=search, args=(q,)) for q in ("Loop", "Near North Side")]
        for thread in searches:
            thread.start()
        for thread in searches:
            thread.join(timeout=10)
        assert len(transport.urls) == 2
        # One left at once; the other waited for the next second.
        assert len(slept) == 1 and 0 < slept[0] <= places.MIN_INTERVAL_S

    def test_a_search_waiting_on_nominatim_does_not_hold_up_a_cached_place(self, monkeypatch):
        """Nominatim can take seconds to answer. Meanwhile a place already
        found is answered at once, from the cache."""
        monkeypatch.setattr(places, "MIN_INTERVAL_S", 0.0)
        places.search_places(_Counting(), "Loop, Chicago")
        asked, release = threading.Event(), threading.Event()

        class Slow(_Counting):
            def json_get(self, url, *, credential=None, headers=None):
                asked.set()
                release.wait(timeout=30)
                return super().json_get(url, credential=credential, headers=headers)

        cached = _Counting()
        answered: list = []
        slow = threading.Thread(target=places.search_places, args=(Slow(), "Near North Side"), daemon=True)
        hit = threading.Thread(
            target=lambda: answered.append(places.search_places(cached, "Loop, Chicago")), daemon=True
        )
        try:
            slow.start()
            assert asked.wait(timeout=10)
            hit.start()
            hit.join(timeout=5)
            assert answered, "a cached place waited for another search's request to Nominatim"
            assert answered[0][0]["name"] == "Loop"
            assert cached.urls == []
        finally:
            release.set()
            slow.join(timeout=10)
            hit.join(timeout=10)

    def test_an_empty_query_asks_nothing(self):
        transport = _Counting()
        assert places.search_places(transport, "   ") == []
        assert transport.urls == []

    def test_an_answer_that_is_not_a_list_is_a_provider_error(self):
        with pytest.raises(ProviderError):
            places.search_places(_Counting(answer={"error": "busy"}), "Loop")

    def test_a_place_without_a_usable_box_is_left_out(self):
        bad = [{"name": "Nowhere", "boundingbox": ["x", "1", "2", "3"]}]
        assert places.search_places(_Counting(answer=bad), "Nowhere") == []


class TestTheRoute:
    def test_it_answers_from_the_recorded_corpus(self, client, auth, fixture_corpus):
        body = client.get("/api/discovery/places?q=Loop, Chicago", headers=auth).get_json()
        assert body["places"][0]["name"] == "Loop"
        assert body["places"][0]["boundary"] is True

    def test_nothing_found_is_an_empty_list(self, client, auth, fixture_corpus):
        body = client.get("/api/discovery/places?q=Nowhere at all", headers=auth).get_json()
        assert body == {"places": []}

    def test_it_needs_a_signed_in_caller(self, client):
        assert client.get("/api/discovery/places?q=Loop").status_code == 401
