from triagesim.cohort.sources import check_data, load_tables


def test_check_finds_nested_files(data_dir):
    assert all(r.ok for r in check_data(data_dir))


def test_check_reports_missing_file(data_dir):
    (data_dir / "mimic-iv-ed-2.2/ed/triage.csv.gz").unlink()
    bad = [r for r in check_data(data_dir) if not r.ok]
    assert [r.table.key for r in bad] == ["triage"]


def test_check_reports_missing_column(data_dir, tables):
    tables["patients"].drop(columns="anchor_year").to_csv(
        data_dir / "mimic-iv-3.1/hosp/patients.csv.gz", index=False)
    bad = [r for r in check_data(data_dir) if not r.ok]
    assert "anchor_year" in bad[0].message


def test_check_missing_folder(tmp_path):
    assert not any(r.ok for r in check_data(tmp_path / "nope"))


def test_load_tables(data_dir):
    assert set(load_tables(data_dir)) == {"patients", "edstays", "triage", "ed_diagnosis"}
