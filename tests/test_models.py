"""The dimensions drawn on the 3D models, checked against the numbers they are labelled with."""

import json
import math

import pytest

from meridian import config

MODELS = json.loads((config.KB / "models" / "index.json").read_text())
DRAWN = [(drawing, d) for drawing, model in MODELS.items() for d in model["dimensions"] if d["at"]]


@pytest.mark.parametrize("drawing, dimension", DRAWN, ids=[f"{m}: {d['name']}" for m, d in DRAWN])
def test_a_drawn_dimension_is_as_long_as_its_label(drawing, dimension):
    a, b = dimension["at"]["a"], dimension["at"]["b"]
    assert math.dist(a, b) == pytest.approx(dimension["value"], abs=0.01)


def test_every_dimension_read_from_the_sheet_points_back_to_it():
    for model in MODELS.values():
        for d in model["dimensions"]:
            assert d["region"] or d["how"] == "as drawn", d["name"]
