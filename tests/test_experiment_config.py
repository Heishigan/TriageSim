from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from triagesim.experiment.config import ExperimentConfig
from triagesim.experiment.fields import case_values, render

PRESETS = sorted(Path("configs/experiments").glob("*.yaml"))


@pytest.mark.parametrize("path", PRESETS, ids=lambda p: p.stem)
def test_presets_are_valid(path):
    ExperimentConfig.from_yaml(path)


def preset(name="interview"):
    return yaml.safe_load(Path(f"configs/experiments/{name}.yaml").read_text())


def test_prompt_cannot_use_a_field_the_agent_does_not_see():
    data = preset()
    data["nurse"]["sees"].remove("vitals")
    with pytest.raises(ValidationError, match="may not see"):
        ExperimentConfig.model_validate(data)


def test_nurse_and_patient_cannot_see_answers():
    data = preset()
    data["nurse"]["sees"].append("esi")
    with pytest.raises(ValidationError, match="reference answers"):
        ExperimentConfig.model_validate(data)
    data = preset()
    data["patient"]["sees"].append("head_injury")
    with pytest.raises(ValidationError, match="reference answers"):
        ExperimentConfig.model_validate(data)


def test_typos_and_unknown_personas_are_errors():
    data = preset()
    data["nurse"]["max_turn"] = 5
    with pytest.raises(ValidationError, match="max_turn"):
        ExperimentConfig.model_validate(data)
    data = preset()
    data["patient"]["persona"] = "grumpy"
    with pytest.raises(ValidationError, match="grumpy"):
        ExperimentConfig.model_validate(data)


def test_interview_needs_a_patient():
    data = preset()
    del data["patient"]
    with pytest.raises(ValidationError, match="needs a patient"):
        ExperimentConfig.model_validate(data)


def test_render_only_fills_allowed_fields(tables, case_tables, notes):
    from triagesim.cases.build import CaseSettings, build_cases
    from triagesim.cohort.build import build_cohort
    from triagesim.cohort.settings import CohortSettings
    cohort = build_cohort(tables, CohortSettings.from_yaml("configs/cohorts/elderly_falls.yaml")).cohort
    case = build_cases(cohort, case_tables, notes, CaseSettings())[0][0]
    values = case_values(case, persona="calm")
    text = render("{age} {sex} {medications}", values, {"age", "sex", "medications"})
    assert text == "70 female Apixaban, Lisinopril"
    with pytest.raises(KeyError):
        render("{esi}", values, {"age"})


def test_round_trip(tmp_path):
    c = ExperimentConfig.from_yaml("configs/experiments/interview.yaml")
    c.to_yaml(tmp_path / "x.yaml")
    assert ExperimentConfig.from_yaml(tmp_path / "x.yaml") == c
