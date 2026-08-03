import re

from app.models import RegexDetection

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
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


def _extract_unit_spans(text: str) -> list[tuple[int, int]]:
    return [m.span(1) for m in UNIT_PATTERN.finditer(text)]


def _extract_number_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in NUMBER_PATTERN.finditer(text)]


def _extract_date_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in DATE_PATTERN.finditer(text)]


def detect_date_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_dates = _extract_dates(old_text)
    new_dates = _extract_dates(new_text)
    if old_dates != new_dates:
        return RegexDetection(
            change_type="date_change",
            reason=f"Date changed from {', '.join(old_dates)} to {', '.join(new_dates)}.",
            old_values=old_dates,
            new_values=new_dates,
            old_spans=_extract_date_spans(old_text),
            new_spans=_extract_date_spans(new_text),
        )
    return None


def detect_unit_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_units = _extract_units(old_text)
    new_units = _extract_units(new_text)
    if old_units != new_units:
        return RegexDetection(
            change_type="unit_change",
            reason=f"Unit changed from {old_units} to {new_units}.",
            old_values=old_units,
            new_values=new_units,
            old_spans=_extract_unit_spans(old_text),
            new_spans=_extract_unit_spans(new_text),
        )
    return None


def detect_numeric_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_numbers = _extract_numbers(old_text)
    new_numbers = _extract_numbers(new_text)
    if old_numbers != new_numbers:
        return RegexDetection(
            change_type="numeric_change",
            reason=f"Numeric value(s) changed from {', '.join(old_numbers)} to {', '.join(new_numbers)}.",
            old_values=old_numbers,
            new_values=new_numbers,
            old_spans=_extract_number_spans(old_text),
            new_spans=_extract_number_spans(new_text),
        )
    return None


def detect_regex_change(old_text: str, new_text: str) -> RegexDetection | None:
    for detector in (detect_date_change, detect_unit_change, detect_numeric_change):
        result = detector(old_text, new_text)
        if result:
            return result
    return None


def detect_all_regex_changes(old_text: str, new_text: str) -> list[RegexDetection]:
    detections = []
    for detector in (detect_date_change, detect_unit_change, detect_numeric_change):
        result = detector(old_text, new_text)
        if result:
            detections.append(result)
    return detections


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + text[end:]
    return text


def strip_detected_values(old_text: str, new_text: str, detections: list["RegexDetection"]) -> tuple[str, str]:
    old_spans = [span for d in detections for span in d.old_spans]
    new_spans = [span for d in detections for span in d.new_spans]
    return _remove_spans(old_text, old_spans), _remove_spans(new_text, new_spans)
