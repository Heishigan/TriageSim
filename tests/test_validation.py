"""Input validation: bad form values, bad presets, damaged or duplicate files."""
import gzip

import pytest

from triagesim.cli import main
from triagesim.cohort.build import build_cohort, save_result
from triagesim.cohort.icd import parse_code_list
from triagesim.cohort.settings import CohortSettings
from triagesim.cohort.sources import DataLoadError, check_data, load_tables


# ---- ICD codes in the wrong box ----------------------------------------------
def test_icd10_code_in_icd9_box_is_rejected():
    with pytest.raises(ValueError, match="ICD-9"):
        parse_code_list("W00-W19", version=9)


def test_icd9_code_in_icd10_box_is_rejected():
    # Numeric ICD-9 codes are caught. ICD-9 E/V codes cannot be: E and V are also
    # valid first letters in ICD-10 (E00-E89 endocrine, V00-V99 transport accidents).
    with pytest.raises(ValueError, match="ICD-10"):
        parse_code_list("850-854", version=10)


def test_valid_codes_per_version():
    assert parse_code_list("E880-E888, V15, 850-854", version=9) == ["E880-E888", "V15", "850-854"]
    assert parse_code_list("W00-W19, S06, S06", version=10) == ["W00-W19", "S06"]


# ---- Bad preset files ----------------------------------------------------------
@pytest.mark.parametrize("yaml_text, message", [
    ("name: x\nmin_age: sixty\n", "min_age"),
    ("name: x\nrequire_acuity: maybe\n", "require_acuity"),
    ("name: x\nesi_levels: [1, two]\n", "esi_levels"),
    ("name: x\nicd9_codes: [W19]\n", "ICD-9"),
    ("name: [unclosed\n", "not valid YAML"),
    ("- just\n- a list\n", "key: value"),
])
def test_bad_preset_gives_readable_error(tmp_path, yaml_text, message):
    (tmp_path / "bad.yaml").write_text(yaml_text)
    with pytest.raises(ValueError, match=message):
        CohortSettings.from_yaml(tmp_path / "bad.yaml")


def test_preset_codes_with_dots_are_normalized(tmp_path):
    (tmp_path / "p.yaml").write_text("name: x\nicd9_codes: ['E888.9']\n")
    assert CohortSettings.from_yaml(tmp_path / "p.yaml").icd9_codes == ["E8889"]


# ---- Damaged and duplicate files -------------------------------------------------
def test_incomplete_download_gives_readable_error(data_dir):
    path = data_dir / "mimic-iv-ed-2.2/ed/edstays.csv.gz"
    header = "subject_id,hadm_id,stay_id,intime\n"
    rows = "".join(f"{i},{i * 7919 % 100003},{i * 104729 % 1000003},2150-01-01\n" for i in range(200_000))
    big = gzip.compress((header + rows).encode())
    path.write_bytes(big[: len(big) // 2])               # a download stopped halfway
    assert all(r.ok for r in check_data(data_dir))      # the header is still readable
    with pytest.raises(DataLoadError, match="edstays.csv.gz.*download it again"):
        load_tables(data_dir)


def test_empty_file_fails_the_check(data_dir):
    (data_dir / "mimic-iv-ed-2.2/ed/triage.csv.gz").write_bytes(b"")
    bad = [r for r in check_data(data_dir) if not r.ok]
    assert bad[0].table.key == "triage" and "Download it again" in bad[0].message


def test_duplicate_copies_are_reported(data_dir):
    src = data_dir / "mimic-iv-3.1/hosp/patients.csv.gz"
    copy = data_dir / "old/mimic-iv-2.2/hosp/patients.csv.gz"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(src.read_bytes())
    patients = next(r for r in check_data(data_dir) if r.table.key == "patients")
    assert patients.ok and "2 copies found" in patients.note


def test_data_folder_is_a_file(tmp_path):
    (tmp_path / "file.txt").write_text("x")
    assert not any(r.ok for r in check_data(tmp_path / "file.txt"))


# ---- Build and save ------------------------------------------------------------
def test_empty_result_is_flagged(tables):
    result = build_cohort(tables, CohortSettings(icd10_codes=["Z99"]))
    assert result.empty_steps() == ["ICD code match in ED diagnoses"]
    assert len(result.cohort) == 0


def test_two_builds_in_the_same_second_do_not_collide(tables, tmp_path):
    s = CohortSettings(name="same")
    result = build_cohort(tables, s)
    first, second = save_result(result, s, tmp_path), save_result(result, s, tmp_path)
    assert first != second and second.exists()


def test_cli_reports_bad_settings_without_crashing(data_dir, tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text("name: x\nmin_age: sixty\n")
    assert main(["cohort", "build", "--settings", str(tmp_path / "bad.yaml"), "--data", str(data_dir)]) == 1
    assert "min_age" in capsys.readouterr().err


def test_cli_reports_missing_data_without_crashing(tmp_path, capsys):
    assert main(["cohort", "build", "--settings", "configs/elderly_falls.yaml", "--data", str(tmp_path)]) == 1
    assert "Data check failed" in capsys.readouterr().err
