import re
import uuid

from app import risk_rules
from app.models import Change, Section, SectionMatch

_HEADING_NUMBER_PATTERN = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+(?P<rest>.*)$")


def _split_heading_number(heading: str) -> tuple[str, str] | None:
    match = _HEADING_NUMBER_PATTERN.match(heading)
    if not match:
        return None
    return match.group("num"), " ".join(match.group("rest").split())


def detect_section_renumbering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for m in matches:
        old_heading = old_sections[m.old_index].heading
        new_heading = new_sections[m.new_index].heading
        old_split = _split_heading_number(old_heading)
        new_split = _split_heading_number(new_heading)
        if old_split is None or new_split is None:
            continue
        old_num, old_rest = old_split
        new_num, new_rest = new_split
        if old_num == new_num or old_rest != new_rest:
            continue
        change_type = "section_renumbered"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=new_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section renumbered from '{old_num}' to '{new_num}'.", source="Body",
        ))
    return changes
