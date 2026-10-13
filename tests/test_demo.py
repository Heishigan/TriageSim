from triagesim.cohort.sources import check_data
from triagesim.demo_data import make_demo_data


def test_demo_data_passes_every_check(tmp_path):
    make_demo_data(tmp_path / "data")
    assert all(r.ok for r in check_data(tmp_path / "data", ("cohort", "cases", "labels")))
