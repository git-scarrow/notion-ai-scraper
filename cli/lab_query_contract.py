"""Validator for Lab Query agent responses against the canonicality contract.

A count/distribution answer must place one of the SCOPE_LABELS within ~50
characters before any number that is followed by a count-bearing noun
("total", "matches", "matching", "results", "rows", "items", "records").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tool_catalog import SCOPE_LABELS


_COUNT_PATTERN = re.compile(
    r"\b(\d[\d,]*)\s+(total|totals|matches|matching|results|rows|items|records)\b",
    re.IGNORECASE,
)
_PROXIMITY_CHARS = 50


@dataclass
class ValidationResult:
    ok: bool
    scope_labels_found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "scope_labels_found": self.scope_labels_found,
            "warnings": self.warnings,
        }


def _has_label_nearby(text: str, number_start: int) -> str | None:
    window_start = max(0, number_start - _PROXIMITY_CHARS)
    window = text[window_start:number_start].lower()
    for label in SCOPE_LABELS:
        if label in window:
            return label
    return None


def validate_count_answer(text: str) -> dict:
    """Validate that count-bearing claims in `text` carry a scope label.

    Returns a dict with `ok`, `scope_labels_found`, and `warnings`.
    """
    if not text or not text.strip():
        return ValidationResult(ok=True).to_dict()

    found: list[str] = []
    warnings: list[str] = []

    for match in _COUNT_PATTERN.finditer(text):
        number = match.group(1)
        noun = match.group(2)
        label = _has_label_nearby(text, match.start())
        if label is None:
            warnings.append(
                f"'{number} {noun}' has no scope label "
                f"({', '.join(SCOPE_LABELS)}) within {_PROXIMITY_CHARS} chars."
            )
        else:
            found.append(label)

    lowered = text.lower()
    for label in SCOPE_LABELS:
        if label in lowered and label not in found:
            found.append(label)

    return ValidationResult(
        ok=not warnings,
        scope_labels_found=sorted(set(found)),
        warnings=warnings,
    ).to_dict()
