from triagesim.cohort.sources import check_data, ensure_layout, layout_tree, load_tables


def test_check_ok_in_required_layout(data_dir):
    assert all(r.ok for r in check_data(data_dir))


def test_missing_file_names_its_place(data_dir):
    (data_dir / "ed/triage.csv.gz").unlink()
    bad = [r for r in check_data(data_dir) if not r.ok]
    assert [r.table.key for r in bad] == ["triage"]
    assert "place it at data/ed/triage.csv.gz" in bad[0].message


def test_misplaced_file_says_where_to_move_it(data_dir):
    wrong = data_dir / "mimic-iv-3.1/hosp/patients.csv.gz"
    wrong.parent.mkdir(parents=True)
    (data_dir / "hosp/patients.csv.gz").rename(wrong)
    bad = [r for r in check_data(data_dir) if not r.ok]
    assert bad[0].message == ("Found at data/mimic-iv-3.1/hosp/patients.csv.gz. "
                              "Move it to data/hosp/patients.csv.gz.")


def test_check_reports_missing_column(data_dir, tables):
    tables["patients"].drop(columns="anchor_year").to_csv(data_dir / "hosp/patients.csv.gz", index=False)
    bad = [r for r in check_data(data_dir) if not r.ok]
    assert "anchor_year" in bad[0].message


def test_check_missing_folder(tmp_path):
    assert not any(r.ok for r in check_data(tmp_path / "nope"))


def test_ensure_layout_creates_empty_folders(tmp_path):
    ensure_layout(tmp_path / "data")
    assert (tmp_path / "data/hosp").is_dir() and (tmp_path / "data/ed").is_dir()


def test_layout_tree_lists_every_file():
    tree = layout_tree()
    for name in ["hosp/", "patients.csv.gz", "ed/", "edstays.csv.gz", "triage.csv.gz", "diagnosis.csv.gz"]:
        assert name in tree


def test_load_tables(data_dir):
    assert set(load_tables(data_dir)) == {"patients", "edstays", "triage", "ed_diagnosis"}
