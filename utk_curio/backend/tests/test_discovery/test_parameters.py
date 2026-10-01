"""Declared parameters: what a manifest may declare, and what a request may answer."""
from __future__ import annotations

import pytest

from utk_curio.backend.app.discovery.domain import parameters as P


def _declare(*entries):
    return P.parse_parameters(list(entries), where="parameters")


AREA = {"id": "area", "type": "area", "label": "Area", "required": True, "maxAreaKm2": 4}
NAMED_AREA = {"id": "area", "type": "area", "label": "Area", "required": True, "accepts": ["box", "names"]}
LOOP_BOX = [-87.640, 41.875, -87.620, 41.890]


class TestManifest:
    def test_every_type_parses(self):
        specs = _declare(
            AREA,
            {"id": "captured", "type": "dateRange", "label": "Captured", "minDate": "2014-01-01"},
            {"id": "size", "type": "choice", "label": "Size", "default": "1024",
             "options": [{"value": "256"}, {"value": "1024"}]},
            {"id": "spacing", "type": "number", "label": "Spacing", "min": 10, "max": 500, "unit": "m"},
            {"id": "maxImages", "type": "integer", "label": "Images", "min": 1, "max": 1000, "default": 50},
            {"id": "panoramasOnly", "type": "boolean", "label": "Panoramas only"},
            {"id": "tags", "type": "text", "label": "Tags", "pattern": r"[a-z_]+"},
            {"id": "link", "type": "url", "label": "Link"},
        )
        assert [s.type for s in specs] == list(P.PARAMETER_TYPES)
        assert specs[2].default == "1024" and specs[4].default == 50

    @pytest.mark.parametrize("entry, says", [
        ({"id": "Area", "type": "area", "label": "A"}, "camelCase"),
        ({"id": "a", "type": "polygon", "label": "A"}, "type must be one of"),
        ({"id": "a", "type": "area"}, "label"),
        ({"id": "a", "type": "number", "label": "A", "min": 5, "max": 1}, "greater than max"),
        ({"id": "a", "type": "text", "label": "A", "min": 1}, "numbers only"),
        ({"id": "a", "type": "choice", "label": "A", "options": []}, "1 to"),
        ({"id": "a", "type": "choice", "label": "A", "options": [{"value": "x"}, {"value": "x"}]}, "repeats"),
        ({"id": "a", "type": "number", "label": "A", "options": [{"value": "x"}]}, "choice only"),
        ({"id": "a", "type": "area", "label": "A", "accepts": ["circle"]}, "accepts"),
        ({"id": "a", "type": "area", "label": "A", "maxAreaKm2": 0}, "positive"),
        ({"id": "a", "type": "text", "label": "A", "pattern": "("}, "regular expression"),
        ({"id": "a", "type": "dateRange", "label": "A", "minDate": "2024-13-01"}, "date like"),
        ({"id": "a", "type": "integer", "label": "A", "max": 3, "default": 9}, "at most 3"),
    ])
    def test_refusals_name_the_problem(self, entry, says):
        with pytest.raises(P.ManifestParameterError, match=says):
            _declare(entry)

    def test_an_id_is_declared_once(self):
        with pytest.raises(P.ManifestParameterError, match="used twice"):
            _declare(AREA, AREA)

    def test_a_resource_entry_replaces_the_sources_by_id(self):
        source = _declare(AREA, {"id": "size", "type": "choice", "label": "Size", "options": [{"value": "1"}]})
        resource = _declare({**AREA, "maxAreaKm2": 25}, {"id": "layer", "type": "text", "label": "Layer"})
        merged = P.merge(source, resource)
        assert [s.id for s in merged] == ["area", "size", "layer"]
        assert merged[0].max_area_km2 == 25


class TestValues:
    def test_unknown_answers_are_refused(self):
        with pytest.raises(P.ParameterError, match="no parameter named secret"):
            P.validate_values(_declare(AREA), {"area": {"box": LOOP_BOX}, "secret": 1})

    def test_required_and_defaults(self):
        declared = _declare(AREA, {"id": "n", "type": "integer", "label": "N", "default": 5})
        with pytest.raises(P.ParameterError, match="Area is required"):
            P.validate_values(declared, {})
        assert P.validate_values(declared, {"area": {"box": LOOP_BOX}})["n"] == 5

    def test_a_box_is_rounded_and_bounded(self):
        out = P.validate_values(_declare(AREA), {"area": {"box": [-87.6400001, 41.875, -87.62, 41.89],
                                                          "label": " Loop "}})
        assert out["area"] == {"box": [-87.64, 41.875, -87.62, 41.89], "label": "Loop"}

    @pytest.mark.parametrize("box", [
        [-87.62, 41.875, -87.64, 41.89],      # west right of east
        [-87.64, 41.89, -87.62, 41.875],      # south above north
        [-190, 0, 0, 1],                      # off the map
        [0, 0, 1],                            # three numbers
        [0, 0, "1", 1],                       # a string
        [0, 0, float("nan"), 1],
    ])
    def test_a_bad_box_is_refused(self, box):
        with pytest.raises(P.ParameterError):
            P.validate_values(_declare(AREA), {"area": {"box": box}})

    def test_an_oversized_box_names_its_size_and_the_limit(self):
        with pytest.raises(P.ParameterError, match=r"km2; this source takes at most 4 km2"):
            P.validate_values(_declare(AREA), {"area": {"box": [-88, 41, -87, 42]}})

    def test_names_only_where_declared(self):
        with pytest.raises(P.ParameterError, match="given as a box"):
            P.validate_values(_declare(AREA), {"area": {"names": {"geocodeArea": "Chicago", "areas": ["Loop"]}}})
        out = P.validate_values(_declare(NAMED_AREA),
                                {"area": {"names": {"geocodeArea": " Chicago ", "areas": ["Loop", "Loop", "Near North Side"]}}})
        assert out["area"] == {"names": {"geocodeArea": "Chicago", "areas": ["Loop", "Near North Side"]}}

    @pytest.mark.parametrize("name", ['Loop"]; out;', "Loop]", "Lo\\op", "a\nb", "x" * 200, ""])
    def test_a_name_cannot_change_the_overpass_query(self, name):
        with pytest.raises(P.ParameterError):
            P.validate_values(_declare(NAMED_AREA), {"area": {"names": {"geocodeArea": "Chicago", "areas": [name]}}})

    def test_choices(self):
        multi = _declare({"id": "h", "type": "choice", "label": "Headings", "multiple": True,
                          "options": [{"value": "0"}, {"value": "90"}, {"value": "180"}]})
        assert P.validate_values(multi, {"h": ["90", "0", "90"]})["h"] == ["0", "90"]
        with pytest.raises(P.ParameterError, match="does not offer 45"):
            P.validate_values(multi, {"h": ["45"]})

    def test_numbers(self):
        declared = _declare({"id": "n", "type": "integer", "label": "N", "min": 1, "max": 10},
                            {"id": "x", "type": "number", "label": "X"})
        assert P.validate_values(declared, {"n": 3.0, "x": 2})["n"] == 3
        for bad in (0, 11, 2.5, True, "3"):
            with pytest.raises(P.ParameterError):
                P.validate_values(declared, {"n": bad})

    def test_dates(self):
        declared = _declare({"id": "d", "type": "dateRange", "label": "Captured", "minDate": "2014-01-01"})
        assert P.validate_values(declared, {"d": {"start": "2024-01-01"}})["d"] == {"start": "2024-01-01"}
        for bad in ({"start": "2024-02-01", "end": "2024-01-01"}, {"start": "2013-12-31"},
                    {"start": "01/02/2024"}, {}):
            with pytest.raises(P.ParameterError):
                P.validate_values(declared, {"d": bad})

    def test_text_and_url(self):
        declared = _declare({"id": "t", "type": "text", "label": "Tag", "pattern": r"[a-z]+=[a-z]+"},
                            {"id": "u", "type": "url", "label": "Link"})
        assert P.validate_values(declared, {"t": " amenity=school ", "u": "https://x.org/a.csv"})["t"] == "amenity=school"
        with pytest.raises(P.ParameterError, match="not in the form"):
            P.validate_values(declared, {"t": 'amenity="school"'})
        with pytest.raises(P.ParameterError, match="https"):
            P.validate_values(declared, {"u": "http://x.org/a.csv"})


class TestIdentity:
    def test_equal_answers_hash_equal_and_labels_do_not_count(self):
        declared = _declare(AREA)
        a = P.validate_values(declared, {"area": {"box": LOOP_BOX, "label": "Loop"}})
        b = P.validate_values(declared, {"area": {"box": [v + 1e-7 for v in LOOP_BOX], "label": "Chicago Loop"}})
        assert P.values_hash(a) == P.values_hash(b)

    def test_different_answers_hash_differently(self):
        declared = _declare(AREA)
        a = P.validate_values(declared, {"area": {"box": LOOP_BOX}})
        b = P.validate_values(declared, {"area": {"box": [-87.645, 41.875, -87.62, 41.89]}})
        assert P.values_hash(a) != P.values_hash(b)

    def test_the_area_of_a_box(self):
        # One degree of latitude by one of longitude at the equator: about 12,364 km2.
        assert P.box_area_km2([0, 0, 1, 1]) == pytest.approx(12364, rel=0.01)
