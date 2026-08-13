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
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section renumbered from '{old_num}' to '{new_num}'.", source="Body",
        ))
    return changes


def _longest_increasing_subsequence_indices(values: list[int]) -> set[int]:
    if not values:
        return set()

    n = len(values)
    lengths = [1] * n
    predecessors = [-1] * n

    for i in range(n):
        for j in range(i):
            if values[j] < values[i] and lengths[j] + 1 > lengths[i]:
                lengths[i] = lengths[j] + 1
                predecessors[i] = j

    best_end = max(range(n), key=lambda i: lengths[i])
    kept = set()
    i = best_end
    while i != -1:
        kept.add(i)
        i = predecessors[i]
    return kept


_SYNTHETIC_HEADING_PATTERN = re.compile(r"^Paragraph \d+$")


def is_synthetic_heading(heading: str) -> bool:
    return heading == "Preamble" or bool(_SYNTHETIC_HEADING_PATTERN.match(heading))


def detect_section_reordering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]:
    if not matches:
        return []

    ordered = sorted(matches, key=lambda m: m.old_index)
    new_index_sequence = [m.new_index for m in ordered]
    kept_positions = _longest_increasing_subsequence_indices(new_index_sequence)

    changes: list[Change] = []
    for i, m in enumerate(ordered):
        if i in kept_positions:
            continue
        old_heading = old_sections[m.old_index].heading
        new_heading = new_sections[m.new_index].heading
        if is_synthetic_heading(old_heading) or is_synthetic_heading(new_heading):
            continue
        change_type = "section_reordered"
        reason = (
            f"Section moved from position {m.old_index + 1} to "
            f"position {m.new_index + 1} in the document."
        )
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source="Body",
        ))
    return changes


def detect_section_added(
    inserted_indices: list[int],
    new_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for idx in inserted_indices:
        section = new_sections[idx]
        if is_synthetic_heading(section.heading):
            continue
        change_type = "section_added"
        new_text = "\n".join([section.heading] + [p.text for p in section.paragraphs])
        new_page = section.paragraphs[0].page if section.paragraphs else None
        source = "Table" if any(p.from_table for p in section.paragraphs) else "Body"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section.heading, change_type=change_type,
            old_text="", new_text=new_text, old_page=None, new_page=new_page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"New section added: '{section.heading}'.", source=source,
        ))
    return changes


def detect_section_deleted(
    deleted_indices: list[int],
    old_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for idx in deleted_indices:
        section = old_sections[idx]
        if is_synthetic_heading(section.heading):
            continue
        change_type = "section_deleted"
        old_text = "\n".join([section.heading] + [p.text for p in section.paragraphs])
        old_page = section.paragraphs[0].page if section.paragraphs else None
        source = "Table" if any(p.from_table for p in section.paragraphs) else "Body"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section.heading, change_type=change_type,
            old_text=old_text, new_text="", old_page=old_page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section deleted: '{section.heading}'.", source=source,
        ))
    return changes
