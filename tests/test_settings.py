import pytest

from triagesim.cohort.settings import CohortSettings


def test_yaml_round_trip(tmp_path):
    s = CohortSettings(name="x", min_age=65, icd10_codes=["W00-W19"], one_visit_per_patient=True)
    s.to_yaml(tmp_path / "s.yaml")
    assert CohortSettings.from_yaml(tmp_path / "s.yaml") == s


def test_preset_loads():
    s = CohortSettings.from_yaml("configs/cohorts/elderly_falls.yaml")
    assert s.min_age == 65 and s.admission == "admitted"


@pytest.mark.parametrize("kwargs", [
    {"min_age": 80, "max_age": 70}, {"sexes": []}, {"sexes": ["X"]},
    {"admission": "maybe"}, {"esi_levels": [6]}, {"icd10_codes": ["W19-W00"]}, {"name": "a b"},
])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        CohortSettings(**kwargs).validate()


def test_unknown_key_in_yaml(tmp_path):
    (tmp_path / "s.yaml").write_text("name: x\nmin_agee: 65\n")
    with pytest.raises(ValueError, match="min_agee"):
        CohortSettings.from_yaml(tmp_path / "s.yaml")
