"""Cohort settings: what the user chooses in the UI or in a YAML file."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .icd import normalize, validate_spec

SEXES = ("F", "M")
ADMISSION_CHOICES = ("any", "admitted", "not_admitted")
ESI_LEVELS = (1, 2, 3, 4, 5)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_types(s: "CohortSettings") -> None:
    problems = []
    if not isinstance(s.name, str):
        problems.append("name must be text")
    for key in ("min_age", "max_age"):
        if getattr(s, key) is not None and not _is_int(getattr(s, key)):
            problems.append(f"{key} must be a whole number or empty")
    for key in ("sexes", "icd10_codes", "icd9_codes"):
        value = getattr(s, key)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            problems.append(f"{key} must be a list of text values")
    if not isinstance(s.esi_levels, list) or not all(_is_int(v) for v in s.esi_levels):
        problems.append("esi_levels must be a list of whole numbers")
    if not isinstance(s.admission, str):
        problems.append("admission must be text")
    for key in ("require_acuity", "one_visit_per_patient"):
        if not isinstance(getattr(s, key), bool):
            problems.append(f"{key} must be true or false")
    if problems:
        raise ValueError("Invalid settings: " + "; ".join(problems) + ".")


@dataclass
class CohortSettings:
    """All filter choices for one cohort. Defaults keep every ED stay."""

    name: str = "cohort"
    min_age: int | None = None
    max_age: int | None = None
    sexes: list[str] = field(default_factory=lambda: list(SEXES))
    admission: str = "any"
    icd10_codes: list[str] = field(default_factory=list)
    icd9_codes: list[str] = field(default_factory=list)
    require_acuity: bool = False
    esi_levels: list[int] = field(default_factory=lambda: list(ESI_LEVELS))
    one_visit_per_patient: bool = False

    def validate(self) -> None:
        """Raise ValueError with a readable message if a choice is invalid."""
        _check_types(self)
        if not self.name or not self.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Name may contain only letters, digits, '-' and '_'.")
        for label, value in (("Minimum age", self.min_age), ("Maximum age", self.max_age)):
            if value is not None and not 0 <= value <= 120:
                raise ValueError(f"{label} must be between 0 and 120.")
        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValueError("Minimum age is greater than maximum age.")
        if not self.sexes or set(self.sexes) - set(SEXES):
            raise ValueError(f"Sex must be a non-empty selection of {SEXES}.")
        if self.admission not in ADMISSION_CHOICES:
            raise ValueError(f"Admission must be one of {ADMISSION_CHOICES}.")
        for spec in self.icd10_codes:
            validate_spec(spec, version=10)
        for spec in self.icd9_codes:
            validate_spec(spec, version=9)
        if not self.esi_levels or set(self.esi_levels) - set(ESI_LEVELS):
            raise ValueError("ESI levels must be a non-empty selection of 1-5.")

    def describe(self) -> list[str]:
        """The active filters in plain words, in the order they are applied."""
        lines = []
        if self.min_age is not None or self.max_age is not None:
            if self.max_age is None:
                lines.append(f"Age {self.min_age} or older at the ED visit")
            else:
                lines.append(f"Age {self.min_age or 0} to {self.max_age} at the ED visit")
        if set(self.sexes) != set(SEXES):
            lines.append(f"Sex: {', '.join(self.sexes)}")
        if self.admission != "any":
            lines.append("Admitted to hospital" if self.admission == "admitted" else "Not admitted to hospital")
        if self.icd10_codes or self.icd9_codes:
            codes = [f"ICD-10 {', '.join(self.icd10_codes)}"] if self.icd10_codes else []
            codes += [f"ICD-9 {', '.join(self.icd9_codes)}"] if self.icd9_codes else []
            lines.append("ED diagnosis includes " + " or ".join(codes))
        if self.require_acuity:
            lines.append("Triage acuity (ESI) recorded")
        if set(self.esi_levels) != set(ESI_LEVELS):
            lines.append(f"ESI level {', '.join(map(str, sorted(self.esi_levels)))}")
        if self.one_visit_per_patient:
            lines.append("First qualifying visit per patient")
        return lines

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(asdict(self), sort_keys=False))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CohortSettings":
        try:
            data = yaml.safe_load(Path(path).read_text()) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{Path(path).name} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{Path(path).name} must contain settings as 'key: value' lines.")
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown setting(s) in {path}: {sorted(unknown)}")
        for key in ("icd10_codes", "icd9_codes"):
            if isinstance(data.get(key), list):
                data[key] = [normalize(str(c)) for c in data[key]]
        settings = cls(**data)
        settings.validate()
        return settings
