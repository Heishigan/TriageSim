import pandas as pd
import pytest

from triagesim.cohort.icd import matches, parse_code_list


def test_parse_normalizes_and_splits():
    assert parse_code_list("w00-w19, e888.9;S06\nE880") == ["W00-W19", "E8889", "S06", "E880"]


@pytest.mark.parametrize("bad", ["W00-W1", "W19-W00", "W00-W10-W19", "S0$"])
def test_parse_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        parse_code_list(bad)


def test_range_and_prefix_matching():
    codes = pd.Series(["W010XXA", "W19", "W20", "E8889", "E888.9", "E880", "E8890", "E9293", "S0600XA"])
    got = matches(codes, ["W00-W19", "E880-E888"]).tolist()
    assert got == [True, True, False, True, True, True, False, False, False]
    assert matches(codes, ["S06"]).tolist() == [False] * 8 + [True]
