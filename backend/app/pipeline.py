import uuid

from app import sectioning, section_matching, paragraph_diff, move_reconciliation
from app import regex_detectors, llm_classifier, risk_rules
from app.models import Paragraph, Change, ComparisonResult, build_summary

Orphan = tuple[Paragraph, str]


def _build_paragraph_change(section_heading: str, old_p: Paragraph, new_p: Paragraph) -> Change:
    change_id = str(uuid.uuid4())
    detection = regex_detectors.detect_regex_change(old_p.text, new_p.text)
    if detection:
        return Change(
            change_id=change_id, section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason,
        )
    return Change(
        change_id=change_id, section=section_heading, change_type="pending_llm_classification",
        old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
        confidence=0.0, ai_risk_level="Medium", reason="",
    )


def compare_documents(
    old_paragraphs: list[Paragraph],
    new_paragraphs: list[Paragraph],
    old_filename: str,
    new_filename: str,
) -> ComparisonResult:
    old_sections = sectioning.split_into_sections(old_paragraphs)
    new_sections = sectioning.split_into_sections(new_paragraphs)
    match_result = section_matching.match_sections(old_sections, new_sections)

    changes: list[Change] = []
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []

    for match in match_result.matches:
        old_sec = old_sections[match.old_index]
        new_sec = new_sections[match.new_index]
        opcodes = paragraph_diff.diff_paragraphs(old_sec.paragraphs, new_sec.paragraphs)

        for op in opcodes:
            if op.tag == "equal":
                continue
            if op.tag == "replace":
                paired = min(len(op.old_paragraphs), len(op.new_paragraphs))
                for i in range(paired):
                    changes.append(_build_paragraph_change(old_sec.heading, op.old_paragraphs[i], op.new_paragraphs[i]))
                orphan_deletes += [(p, old_sec.heading) for p in op.old_paragraphs[paired:]]
                orphan_inserts += [(p, new_sec.heading) for p in op.new_paragraphs[paired:]]
            elif op.tag == "delete":
                orphan_deletes += [(p, old_sec.heading) for p in op.old_paragraphs]
            elif op.tag == "insert":
                orphan_inserts += [(p, new_sec.heading) for p in op.new_paragraphs]

    for idx in match_result.deleted_indices:
        sec = old_sections[idx]
        orphan_deletes += [(p, sec.heading) for p in sec.paragraphs]
    for idx in match_result.inserted_indices:
        sec = new_sections[idx]
        orphan_inserts += [(p, sec.heading) for p in sec.paragraphs]

    moved, remaining_deletes, remaining_inserts = move_reconciliation.reconcile_moves(orphan_deletes, orphan_inserts)

    for mv in moved:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=f"{mv.old_section} -> {mv.new_section}",
            change_type="moved_paragraph", old_text=mv.old_paragraph.text, new_text=mv.new_paragraph.text,
            old_page=mv.old_paragraph.page, new_page=mv.new_paragraph.page, confidence=mv.score,
            ai_risk_level=risk_rules.assign_risk("moved_paragraph"),
            reason=f"Paragraph moved from '{mv.old_section}' to '{mv.new_section}'.",
        ))

    for p, section in remaining_deletes:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type="deleted_paragraph",
            old_text=p.text, new_text="", old_page=p.page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk("deleted_paragraph"),
            reason="Paragraph removed.",
        ))

    for p, section in remaining_inserts:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type="added_paragraph",
            old_text="", new_text=p.text, old_page=None, new_page=p.page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk("added_paragraph"),
            reason="New paragraph added.",
        ))

    pending = [c for c in changes if c.change_type == "pending_llm_classification"]
    if pending:
        classifications = llm_classifier.classify_changes_batch([
            {"change_id": c.change_id, "old_text": c.old_text, "new_text": c.new_text} for c in pending
        ])
        by_id = {cl.change_id: cl for cl in classifications}
        for c in changes:
            cl = by_id.get(c.change_id)
            if cl:
                c.change_type = cl.change_type
                c.reason = cl.reason
                c.confidence = cl.confidence
                c.ai_risk_level = risk_rules.assign_risk(cl.change_type)

    return ComparisonResult(
        comparison_id=str(uuid.uuid4()), old_document=old_filename, new_document=new_filename,
        summary=build_summary(changes), changes=changes,
    )
