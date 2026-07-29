import json

from google import genai

from app import config
from app.models import LLMClassification

SEMANTIC_CHANGE_TYPES = [
    "role_responsibility_change",
    "reference_document_change",
    "qualitative_specification_change",
    "process_sequence_change",
    "clarification_no_meaning_change",
    "formatting_only",
]

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _build_prompt(unresolved: list[dict]) -> str:
    lines = [
        "You are reviewing paired old/new text from a revised pharmaceutical document.",
        "For each item, classify the change into exactly one of these types:",
        *[f"- {t}" for t in SEMANTIC_CHANGE_TYPES],
        "Respond ONLY with a JSON array. Each element must have keys:",
        '"change_id", "change_type", "reason" (one sentence), "confidence" (0.0-1.0).',
        "",
        "Items:",
    ]
    for item in unresolved:
        lines.append(json.dumps({
            "change_id": item["change_id"],
            "old_text": item["old_text"],
            "new_text": item["new_text"],
        }))
    return "\n".join(lines)


def _call_gemini(unresolved: list[dict], model_name: str) -> str:
    client = _get_client()
    response = client.models.generate_content(
        model=model_name,
        contents=_build_prompt(unresolved),
        config={"response_mime_type": "application/json"},
    )
    return response.text


def _parse_response(raw: str, unresolved: list[dict]) -> list[LLMClassification]:
    data = json.loads(raw)
    valid_ids = {item["change_id"] for item in unresolved}
    results = []
    for entry in data:
        if entry.get("change_id") not in valid_ids:
            continue
        results.append(
            LLMClassification(
                change_id=entry["change_id"],
                change_type=entry.get("change_type", "unclassified"),
                reason=entry.get("reason", ""),
                confidence=float(entry.get("confidence", 0.0)),
            )
        )
    return results


def _fallback(unresolved: list[dict]) -> list[LLMClassification]:
    return [
        LLMClassification(
            change_id=item["change_id"],
            change_type="unclassified",
            reason="Automatic classification unavailable — needs manual review.",
            confidence=0.0,
        )
        for item in unresolved
    ]


def classify_changes_batch(unresolved: list[dict]) -> list[LLMClassification]:
    if not unresolved:
        return []
    try:
        raw = _call_gemini(unresolved, config.GEMINI_MODEL)
        return _parse_response(raw, unresolved)
    except Exception:
        return _fallback(unresolved)
