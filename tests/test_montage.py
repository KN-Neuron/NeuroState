import pytest
from pydantic import ValidationError

from neurostate.config import MOCK_CHANNELS
from neurostate.montage import Montage, builtin_montages, load_montage


def test_standard_montage_is_built_in():
    assert "standard-1020" in builtin_montages()
    montage = load_montage("standard-1020")

    assert montage.channels is None
    assert montage.regions.occipital == ["O1", "Oz", "O2"]


def test_region_indices_match_labels_case_insensitively():
    montage = load_montage("standard-1020")
    labels = ["FZ", "f3", "O1", "O2", "Cz"]

    assert montage.region_indices(labels) == {
        "frontal": [0, 1],
        "parietal": [],
        "occipital": [2, 3],
    }


def test_every_standard_region_is_on_the_mock_cap():
    positions = load_montage("standard-1020").region_indices(list(MOCK_CHANNELS))

    assert all(len(found) == 3 for found in positions.values())


def test_montage_loads_from_a_file(tmp_path):
    path = tmp_path / "cap.yaml"
    path.write_text(
        "name: Test cap\nchannels: [Fp1, O1]\nregions:\n  occipital: [O1]\n", encoding="utf-8"
    )

    montage = load_montage(str(path))

    assert montage.name == "Test cap"
    assert montage.channels == ["Fp1", "O1"]
    assert montage.regions.frontal == []


def test_unknown_montage_name_lists_the_built_in_ones():
    with pytest.raises(ValueError, match="standard-1020"):
        load_montage("no-such-cap")


@pytest.mark.parametrize(
    "contents",
    [
        {"name": "x", "channels": ["O1"], "regions": {"occipital": ["O2"]}},
        {"name": "x", "regions": {"temporal": ["T7"]}},
        {"name": "x", "regions": {}, "colour": "blue"},
        {"regions": {}},
    ],
)
def test_invalid_montages_are_rejected(contents):
    with pytest.raises(ValidationError):
        Montage.model_validate(contents)
