"""ICD code parsing and matching.

MIMIC-IV stores ICD codes without dots, for example ``W19XXXA`` (ICD-10) or
``E8889`` (ICD-9). Users may type codes with dots; they are normalized here.

A code specification is either:
  * a prefix, e.g. ``S06`` matches every code starting with S06, or
  * a range, e.g. ``W00-W19`` matches every code whose first three characters
    fall between W00 and W19 (inclusive). Both ends must have the same length.
"""
from __future__ import annotations

import re

import pandas as pd

_VALID = re.compile(r"^[A-Z0-9]+$")


def normalize(code: str) -> str:
    """Upper-case, strip whitespace and remove dots: 'e888.9' -> 'E8889'."""
    return str(code).strip().upper().replace(".", "")


def validate_spec(spec: str, version: int | None = None) -> None:
    """Raise ValueError if ``spec`` is not a valid prefix or range.

    With ``version`` given, also check the code looks like that ICD version:
    ICD-10 codes start with a letter; ICD-9 codes start with a digit, E or V.
    """
    parts = spec.split("-")
    if len(parts) > 2 or not all(_VALID.match(p) for p in parts):
        raise ValueError(f"Invalid ICD code or range: {spec!r}")
    if version == 10 and not all(p[0].isalpha() for p in parts):
        raise ValueError(f"{spec!r} does not look like an ICD-10 code (they start with a letter).")
    if version == 9 and not all(p[0].isdigit() or p[0] in "EV" for p in parts):
        raise ValueError(f"{spec!r} does not look like an ICD-9 code (they start with a digit, E or V).")
    if len(parts) == 2:
        start, end = parts
        if len(start) != len(end):
            raise ValueError(f"Both ends of a range must have the same length: {spec!r}")
        if start > end:
            raise ValueError(f"Range start comes after range end: {spec!r}")


def parse_code_list(text: str, version: int | None = None) -> list[str]:
    """Parse user input such as 'W00-W19, S06' into a list of validated specs."""
    items = [normalize(x) for x in re.split(r"[,;\s]+", text or "") if x.strip()]
    for item in items:
        validate_spec(item, version)
    return list(dict.fromkeys(items))   # drop duplicates, keep order


def matches(codes: pd.Series, specs: list[str]) -> pd.Series:
    """Boolean Series: True where a code matches at least one spec."""
    codes = codes.astype(str).str.strip().str.upper().str.replace(".", "", regex=False)
    result = pd.Series(False, index=codes.index)
    for spec in specs:
        if "-" in spec:
            start, end = spec.split("-")
            prefix = codes.str[: len(start)]
            result |= (codes.str.len() >= len(start)) & prefix.between(start, end)
        else:
            result |= codes.str.startswith(spec)
    return result
