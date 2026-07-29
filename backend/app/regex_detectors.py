import re

from app.models import RegexDetection

NUMBER_PATTERN = re.compile(r"-?\d+\.?\d*")
UNIT_PATTERN = re.compile(r"\d+\.?\d*\s*(%|°C|°F|mL|L|mg|kg|g|min|hr|h|RH)")
DATE_PATTERN = re.compile(
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
    re.IGNORECASE,
)


def _extract_units(text: str) -> list[str]:
    return [m.group(1) for m in UNIT_PATTERN.finditer(text)]


def _extract_numbers(text: str) -> list[str]:
    return NUMBER_PATTERN.findall(text)


def _extract_dates(text: str) -> list[str]:
    return [m.group(0) for m in DATE_PATTERN.finditer(text)]


def detect_date_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_dates = _extract_dates(old_text)
    new_dates = _extract_dates(new_text)
    if old_dates != new_dates:
        return RegexDetection(
            change_type="date_change",
            reason=f"Date changed from {', '.join(old_dates)} to {', '.join(new_dates)}.",
        )
    return None


def detect_unit_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_units = _extract_units(old_text)
    new_units = _extract_units(new_text)
    if old_units != new_units:
        return RegexDetection(
            change_type="unit_change",
            reason=f"Unit changed from {old_units} to {new_units}.",
        )
    return None


def detect_numeric_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_numbers = _extract_numbers(old_text)
    new_numbers = _extract_numbers(new_text)
    if old_numbers != new_numbers:
        return RegexDetection(
            change_type="numeric_change",
            reason=f"Numeric value(s) changed from {', '.join(old_numbers)} to {', '.join(new_numbers)}.",
        )
    return None


def detect_regex_change(old_text: str, new_text: str) -> RegexDetection | None:
    for detector in (detect_date_change, detect_unit_change, detect_numeric_change):
        result = detector(old_text, new_text)
        if result:
            return result
    return None
