import uuid

from app import sectioning, section_matching, section_structure, paragraph_diff, move_reconciliation
from app import regex_detectors, llm_classifier, risk_rules
from app.models import Paragraph, Change, ComparisonResult, build_summary

Orphan = tuple[Paragraph, str]


def _build_paragraph_changes(
    section_heading: str, old_p: Paragraph, new_p: Paragraph
) -> tuple[list[Change], dict[str, list[str]]]:
    source = "Table" if (old_p.from_table or new_p.from_table) else "Body"
    detections = regex_detectors.detect_all_regex_changes(old_p.text, new_p.text)
    changes: list[Change] = []
    for detection in detections:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason, source=source,
        ))

    already_detected_by_id: dict[str, list[str]] = {}
    stripped_old, stripped_new = regex_detectors.strip_detected_values(old_p.text, new_p.text, detections)
    if stripped_old != stripped_new:
        pending_id = str(uuid.uuid4())
        changes.append(Change(
            change_id=pending_id, section=section_heading, change_type="pending_llm_classification",
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=0.0, ai_risk_level="Medium", reason="", source=source,
        ))
        already_detected_by_id[pending_id] = [d.change_type for d in detections]

    return changes, already_detected_by_id


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
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_reordering(
        match_result.matches, old_sections, new_sections
    ))
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []
    already_detected_by_id: dict[str, list[str]] = {}

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
                    para_changes, para_already_detected = _build_paragraph_changes(
                        old_sec.heading, op.old_paragraphs[i], op.new_paragraphs[i]
                    )
                    changes.extend(para_changes)
                    already_detected_by_id.update(para_already_detected)
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
        source = "Table" if (mv.old_paragraph.from_table or mv.new_paragraph.from_table) else "Body"
        if source == "Table":
            change_type = "moved_table_content"
            reason = f"Table content moved from '{mv.old_section}' to '{mv.new_section}'."
        else:
            change_type = "moved_paragraph"
            reason = f"Paragraph moved from '{mv.old_section}' to '{mv.new_section}'."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=f"{mv.old_section} -> {mv.new_section}",
            change_type=change_type, old_text=mv.old_paragraph.text, new_text=mv.new_paragraph.text,
            old_page=mv.old_paragraph.page, new_page=mv.new_paragraph.page, confidence=mv.score,
            ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))

    for p, section in remaining_deletes:
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "deleted_table_content"
            reason = "Table content removed."
        else:
            change_type = "deleted_paragraph"
            reason = "Paragraph removed."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text=p.text, new_text="", old_page=p.page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))

    for p, section in remaining_inserts:
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "added_table_content"
            reason = "New table content added."
        else:
            change_type = "added_paragraph"
            reason = "New paragraph added."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text="", new_text=p.text, old_page=None, new_page=p.page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))

    pending = [c for c in changes if c.change_type == "pending_llm_classification"]
    if pending:
        classifications = llm_classifier.classify_changes_batch([
            {
                "change_id": c.change_id, "old_text": c.old_text, "new_text": c.new_text,
                "already_detected": already_detected_by_id.get(c.change_id, []),
            }
            for c in pending
        ])
        by_id = {cl.change_id: cl for cl in classifications}
        for c in changes:
            if c.change_type != "pending_llm_classification":
                continue
            cl = by_id.get(c.change_id)
            if cl:
                c.change_type = cl.change_type
                c.reason = cl.reason
                c.confidence = cl.confidence
                c.ai_risk_level = risk_rules.assign_risk(cl.change_type)
            else:
                # The batch response didn't cover this change (partial/malformed
                # output) — never let the internal placeholder leak into the report.
                c.change_type = "unclassified"
                c.reason = "Automatic classification unavailable — needs manual review."
                c.confidence = 0.0
                c.ai_risk_level = risk_rules.assign_risk("unclassified")

    return ComparisonResult(
        comparison_id=str(uuid.uuid4()), old_document=old_filename, new_document=new_filename,
        summary=build_summary(changes), changes=changes,
    )
