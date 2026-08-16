import json
import time

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
    # Check if any item has a non-empty already_detected list
    has_already_detected = any(item.get("already_detected") for item in unresolved)

    lines = [
        "You are reviewing paired old/new text from a revised pharmaceutical document.",
        "For each item, classify the change into exactly one of these types:",
        *[f"- {t}" for t in SEMANTIC_CHANGE_TYPES],
        "Respond ONLY with a JSON array. Each element must have keys:",
        '"change_id", "change_type", "reason" (one sentence), "confidence" (0.0-1.0).',
    ]

    if has_already_detected:
        lines.extend([
            "Some items include an \"already_detected\" list -- these are change types a separate",
            "automated check already found for that item. If present, classify only a genuinely",
            "distinct additional change beyond what's already listed; do not restate or",
            "re-describe the already-detected fact.",
        ])

    lines.append("")
    lines.append("Items:")

    for item in unresolved:
        entry = {
            "change_id": item["change_id"],
            "old_text": item["old_text"],
            "new_text": item["new_text"],
        }
        if item.get("already_detected"):
            entry["already_detected"] = item["already_detected"]
        lines.append(json.dumps(entry))
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
        change_type = entry.get("change_type", "unclassified")
        if change_type not in SEMANTIC_CHANGE_TYPES:
            change_type = "unclassified"
        results.append(
            LLMClassification(
                change_id=entry["change_id"],
                change_type=change_type,
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


# Transient server-side conditions worth a retry: 429 (rate limited - the API returns
# this both for short-window limits that clear in seconds and for daily caps that don't,
# and we can't reliably tell them apart from the response), plus the 5xx overload family.
# A 503 "model is overloaded" was observed repeatedly in practice, and without a retry a
# single blip permanently marked otherwise-classifiable changes as "unclassified" in the
# saved report. Anything else (400 bad request, 404 unknown model, a parse failure) will
# not fix itself on a retry, so those fall back immediately.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 2.0


def _is_retryable(exc: Exception) -> bool:
    return getattr(exc, "code", None) in _RETRYABLE_STATUS_CODES


def classify_changes_batch(unresolved: list[dict]) -> list[LLMClassification]:
    if not unresolved:
        return []
    for attempt in range(_MAX_ATTEMPTS):
        try:
            raw = _call_gemini(unresolved, config.GEMINI_MODEL)
            return _parse_response(raw, unresolved)
        except Exception as exc:
            is_last_attempt = attempt == _MAX_ATTEMPTS - 1
            if is_last_attempt or not _is_retryable(exc):
                return _fallback(unresolved)
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
    return _fallback(unresolved)
