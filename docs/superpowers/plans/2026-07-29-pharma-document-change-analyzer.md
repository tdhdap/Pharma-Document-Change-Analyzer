# AI-Assisted Pharmaceutical Document Change Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit + FastAPI + SQLite app, packaged in Docker Compose, that compares two versions of a pharmaceutical document and produces a categorized, risk-scored change report.

**Architecture:** A `backend/` FastAPI service owns all logic (extraction → sectioning → embedding-based section matching → paragraph diffing → move reconciliation → regex/LLM classification → risk rules → SQLite persistence) and exposes it over a small REST API. A `frontend/` Streamlit app is a thin client with four pages, holding no business logic of its own. The two run as separate Docker Compose services sharing a volume for the SQLite file and uploaded documents.

**Tech Stack:** Python 3.11, FastAPI + Uvicorn, Streamlit, SQLite (stdlib `sqlite3`), PyMuPDF, python-docx, sentence-transformers (`all-MiniLM-L6-v2`), `google-genai` (Gemini), pytest, Docker Compose.

## Global Constraints

- Supported input formats: PDF (text-based only), DOCX, TXT. No OCR/scanned-document support (explicitly phase 2, out of scope).
- No authentication, no multi-user support — single-user local/demo tool.
- Comparison runs synchronously inside `POST /compare` — no background jobs, no polling.
- `ai_risk_level` (pipeline-assigned) and `reviewer_risk_level` (nullable, reviewer override) are always stored as separate columns — never overwrite the original AI classification.
- Risk level is always assigned from the fixed rule table in this plan (§ Task 8), even for LLM-classified change types — the LLM decides `change_type`, the table decides risk.
- All Gemini calls happen in exactly one place (`llm_classifier.py`), are batched (one call per comparison, not one per change), and every test that exercises code touching this module mocks it — no live API calls in the test suite.
- `GEMINI_API_KEY` is read from environment/`.env`, never hard-coded or committed.
- Python package layout: `backend/app/` (import as `from app...`, tests run from `backend/`); `frontend/` flat layout (tests run from `frontend/`).

---

### Task 1: Backend Scaffold — FastAPI App, Config, Domain Models, Health Check

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/Dockerfile`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/models.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_health.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `app.config.DB_PATH: str`, `app.config.GEMINI_API_KEY: str`, `app.config.GEMINI_MODEL: str`, `app.config.UPLOAD_DIR: str`
- Produces: `app.models.Paragraph`, `Section`, `SectionMatch`, `SectionMatchResult`, `MovedParagraph`, `RegexDetection`, `LLMClassification`, `Change`, `ComparisonSummary`, `ComparisonResult`, `build_summary(changes: list[Change]) -> ComparisonSummary` — all dataclasses/functions listed below, used by every later task.
- Produces: `app.main.app` (FastAPI instance) with `GET /health`

- [ ] **Step 1: Write `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-multipart==0.0.9
httpx==0.27.2
pymupdf==1.24.10
python-docx==1.1.2
sentence-transformers==3.1.1
numpy==1.26.4
google-genai==0.3.0
pytest==8.3.3
```

- [ ] **Step 2: Write `backend/pytest.ini`**

```ini
[pytest]
pythonpath = .
```

- [ ] **Step 3: Write `backend/app/__init__.py`** (empty file marking `app` as a package)

- [ ] **Step 4: Write `backend/app/config.py`**

```python
import os

DB_PATH = os.environ.get("DB_PATH", "./app.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
```

- [ ] **Step 5: Write the failing test for models**

```python
# backend/tests/test_models.py
from app.models import (
    Paragraph, Section, SectionMatch, SectionMatchResult, MovedParagraph,
    RegexDetection, LLMClassification, Change, ComparisonSummary,
    ComparisonResult, build_summary,
)


def test_paragraph_defaults():
    p = Paragraph(text="hello")
    assert p.text == "hello"
    assert p.page is None
    assert p.paragraph_index is None


def test_section_holds_paragraphs():
    s = Section(heading="1.0 Scope", paragraphs=[Paragraph(text="a"), Paragraph(text="b")])
    assert s.heading == "1.0 Scope"
    assert len(s.paragraphs) == 2


def test_change_defaults_for_reviewer_fields():
    c = Change(
        change_id="c1", section="1.0 Scope", change_type="numeric_change",
        old_text="95%", new_text="98%", old_page=1, new_page=1,
        confidence=1.0, ai_risk_level="High", reason="value changed",
    )
    assert c.reviewer_risk_level is None
    assert c.reviewer_comment is None
    assert c.accepted is False


def test_build_summary_counts_by_risk():
    changes = [
        Change("1", "s", "t", "o", "n", None, None, 1.0, "High", "r"),
        Change("2", "s", "t", "o", "n", None, None, 1.0, "High", "r"),
        Change("3", "s", "t", "o", "n", None, None, 1.0, "Medium", "r"),
        Change("4", "s", "t", "o", "n", None, None, 1.0, "Informational", "r"),
    ]
    summary = build_summary(changes)
    assert summary.total_changes == 4
    assert summary.high_risk == 2
    assert summary.medium_risk == 1
    assert summary.low_risk == 0
    assert summary.informational == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'` (or similar import error).

- [ ] **Step 7: Write `backend/app/models.py`**

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class Paragraph:
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None


@dataclass
class Section:
    heading: str
    paragraphs: list[Paragraph]


@dataclass
class SectionMatch:
    old_index: int
    new_index: int
    score: float


@dataclass
class SectionMatchResult:
    matches: list[SectionMatch]
    deleted_indices: list[int]
    inserted_indices: list[int]


@dataclass
class MovedParagraph:
    old_paragraph: Paragraph
    new_paragraph: Paragraph
    old_section: str
    new_section: str
    score: float


@dataclass
class RegexDetection:
    change_type: str
    reason: str
    confidence: float = 1.0


@dataclass
class LLMClassification:
    change_id: str
    change_type: str
    reason: str
    confidence: float


@dataclass
class Change:
    change_id: str
    section: str
    change_type: str
    old_text: str
    new_text: str
    old_page: Optional[int]
    new_page: Optional[int]
    confidence: float
    ai_risk_level: str
    reason: str
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: bool = False


@dataclass
class ComparisonSummary:
    total_changes: int
    high_risk: int
    medium_risk: int
    low_risk: int
    informational: int


@dataclass
class ComparisonResult:
    comparison_id: str
    old_document: str
    new_document: str
    summary: ComparisonSummary
    changes: list[Change]


def build_summary(changes: list[Change]) -> ComparisonSummary:
    return ComparisonSummary(
        total_changes=len(changes),
        high_risk=sum(1 for c in changes if c.ai_risk_level == "High"),
        medium_risk=sum(1 for c in changes if c.ai_risk_level == "Medium"),
        low_risk=sum(1 for c in changes if c.ai_risk_level == "Low"),
        informational=sum(1 for c in changes if c.ai_risk_level == "Informational"),
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Write the failing health-check test**

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 11: Write `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Pharma Document Change Analyzer")


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 12: Run test to verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 13: Write `backend/Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model at build time so first request isn't slow
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY app ./app

ENV DB_PATH=/data/app.db
ENV UPLOAD_DIR=/data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 14: Commit**

```bash
git add backend/requirements.txt backend/Dockerfile backend/pytest.ini backend/app/__init__.py backend/app/config.py backend/app/models.py backend/app/main.py backend/tests/test_health.py backend/tests/test_models.py
git commit -m "feat: backend scaffold with config, domain models, health check"
```

---

### Task 2: Text Extraction (PDF / DOCX / TXT)

**Files:**
- Create: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `app.models.Paragraph`
- Produces: `app.extraction.extract_text(file_path: str, file_type: str) -> list[Paragraph]` (`file_type` is one of `"pdf"`, `"docx"`, `"txt"`) — used by `main.py` (Task 13) and `pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_extraction.py
import fitz  # PyMuPDF, used here only to build a test fixture
from docx import Document as DocxDocument

from app.extraction import extract_text


def test_extract_txt_splits_on_blank_lines(tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("First paragraph.\n\nSecond paragraph.\n\nThird paragraph.")

    paragraphs = extract_text(str(file_path), "txt")

    assert [p.text for p in paragraphs] == [
        "First paragraph.", "Second paragraph.", "Third paragraph.",
    ]
    assert paragraphs[0].paragraph_index == 0
    assert paragraphs[2].paragraph_index == 2
    assert all(p.page is None for p in paragraphs)


def test_extract_docx_reads_paragraphs(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Heading One")
    doc.add_paragraph("")  # blank paragraphs should be skipped
    doc.add_paragraph("Body text.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert [p.text for p in paragraphs] == ["Heading One", "Body text."]
    assert paragraphs[0].paragraph_index == 0
    assert paragraphs[1].paragraph_index == 1


def test_extract_pdf_tags_page_numbers(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "Page one text.")
    page2 = pdf.new_page()
    page2.insert_text((72, 72), "Page two text.")
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    assert any(p.page == 1 and "Page one text." in p.text for p in paragraphs)
    assert any(p.page == 2 and "Page two text." in p.text for p in paragraphs)


def test_extract_text_rejects_unknown_type(tmp_path):
    file_path = tmp_path / "doc.xyz"
    file_path.write_text("content")

    try:
        extract_text(str(file_path), "xyz")
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.extraction'`

- [ ] **Step 3: Write `backend/app/extraction.py`**

```python
import fitz
from docx import Document as DocxDocument

from app.models import Paragraph


def extract_text(file_path: str, file_type: str) -> list[Paragraph]:
    if file_type == "pdf":
        return _extract_pdf(file_path)
    if file_type == "docx":
        return _extract_docx(file_path)
    if file_type == "txt":
        return _extract_txt(file_path)
    raise ValueError(f"Unsupported file type: {file_type}")


def _extract_pdf(file_path: str) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    doc = fitz.open(file_path)
    for page_index, page in enumerate(doc):
        text = page.get_text().strip()
        if not text:
            continue
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if chunk:
                paragraphs.append(Paragraph(text=chunk, page=page_index + 1))
    doc.close()
    return paragraphs


def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    paragraphs: list[Paragraph] = []
    index = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        paragraphs.append(Paragraph(text=text, paragraph_index=index))
        index += 1
    return paragraphs


def _extract_txt(file_path: str) -> list[Paragraph]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    paragraphs = []
    for index, chunk in enumerate(content.split("\n\n")):
        chunk = chunk.strip()
        if chunk:
            paragraphs.append(Paragraph(text=chunk, paragraph_index=index))
    return paragraphs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: text extraction for PDF, DOCX, and TXT"
```

---

### Task 3: Document Sectioning

**Files:**
- Create: `backend/app/sectioning.py`
- Test: `backend/tests/test_sectioning.py`

**Interfaces:**
- Consumes: `app.models.Paragraph`, `Section`
- Produces: `app.sectioning.split_into_sections(paragraphs: list[Paragraph]) -> list[Section]` — used by `pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_sectioning.py
from app.models import Paragraph
from app.sectioning import split_into_sections


def test_splits_on_numbered_headings():
    paragraphs = [
        Paragraph(text="5.2 Sample Preparation"),
        Paragraph(text="Weigh 10 mg of sample."),
        Paragraph(text="5.3 Sample Analysis"),
        Paragraph(text="Inject into the HPLC system."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "5.2 Sample Preparation"
    assert [p.text for p in sections[0].paragraphs] == ["Weigh 10 mg of sample."]
    assert sections[1].heading == "5.3 Sample Analysis"
    assert [p.text for p in sections[1].paragraphs] == ["Inject into the HPLC system."]


def test_paragraphs_before_first_heading_become_preamble():
    paragraphs = [
        Paragraph(text="This document describes the sampling procedure."),
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This applies to all raw materials."),
    ]

    sections = split_into_sections(paragraphs)

    assert sections[0].heading == "Preamble"
    assert [p.text for p in sections[0].paragraphs] == [
        "This document describes the sampling procedure."
    ]
    assert sections[1].heading == "1.0 Scope"


def test_no_headings_falls_back_to_one_section_per_paragraph():
    paragraphs = [
        Paragraph(text="Assay acceptance criterion: 95.0% to 105.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C."),
        Paragraph(text="The Quality Control Manager shall approve the result."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 3
    assert sections[0].heading == "Paragraph 1"
    assert sections[0].paragraphs == [paragraphs[0]]
    assert sections[2].heading == "Paragraph 3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sectioning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sectioning'`

- [ ] **Step 3: Write `backend/app/sectioning.py`**

```python
import re

from app.models import Paragraph, Section

HEADING_PATTERN = re.compile(r"^\s*\d+(\.\d+)*\s+\S.*$")
MAX_HEADING_LENGTH = 120


def split_into_sections(paragraphs: list[Paragraph]) -> list[Section]:
    heading_indices = [
        i
        for i, p in enumerate(paragraphs)
        if HEADING_PATTERN.match(p.text) and len(p.text) <= MAX_HEADING_LENGTH
    ]

    if not heading_indices:
        return [
            Section(heading=f"Paragraph {i + 1}", paragraphs=[p])
            for i, p in enumerate(paragraphs)
        ]

    sections: list[Section] = []
    if heading_indices[0] > 0:
        sections.append(Section(heading="Preamble", paragraphs=paragraphs[: heading_indices[0]]))

    for idx, start in enumerate(heading_indices):
        end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(paragraphs)
        heading_text = paragraphs[start].text
        body = paragraphs[start + 1 : end]
        sections.append(Section(heading=heading_text, paragraphs=body))

    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sectioning.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/sectioning.py backend/tests/test_sectioning.py
git commit -m "feat: heading-based document sectioning with paragraph-level fallback"
```

---

### Task 4: Embeddings & Cosine Similarity

**Files:**
- Create: `backend/app/embeddings.py`
- Test: `backend/tests/test_embeddings.py`

**Interfaces:**
- Produces: `app.embeddings.embed_texts(texts: list[str]) -> numpy.ndarray`, `app.embeddings.cosine_similarity_matrix(a: numpy.ndarray, b: numpy.ndarray) -> numpy.ndarray` — used by `section_matching.py` (Task 5) and `move_reconciliation.py` (Task 7).

**Note:** the first run of these tests downloads the `all-MiniLM-L6-v2` model (~80MB) and requires internet access. Subsequent runs use the local cache.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_embeddings.py
from app.embeddings import embed_texts, cosine_similarity_matrix


def test_embed_texts_returns_one_vector_per_input():
    vectors = embed_texts(["hello world", "goodbye world"])
    assert vectors.shape[0] == 2


def test_cosine_similarity_matrix_shape():
    a = embed_texts(["The cat sat on the mat."])
    b = embed_texts(["The dog sat on the mat.", "Quantum entanglement in solid-state physics."])
    scores = cosine_similarity_matrix(a, b)
    assert scores.shape == (1, 2)


def test_similar_sentences_score_higher_than_dissimilar_ones():
    a = embed_texts(["Samples shall be stored at 25 degrees Celsius."])
    b = embed_texts([
        "Samples must be kept at a temperature of 25 degrees Celsius.",
        "The quarterly finance report is due next Tuesday.",
    ])
    scores = cosine_similarity_matrix(a, b)
    assert scores[0][0] > scores[0][1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_embeddings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.embeddings'`

- [ ] **Step 3: Write `backend/app/embeddings.py`**

```python
import numpy as np
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    model = _get_model()
    return model.encode(texts, convert_to_numpy=True)


def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return a_norm @ b_norm.T
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_embeddings.py -v`
Expected: PASS (3 tests) — first run will pause to download the model.

- [ ] **Step 5: Commit**

```bash
git add backend/app/embeddings.py backend/tests/test_embeddings.py
git commit -m "feat: sentence-transformer embeddings and cosine similarity"
```

---

### Task 5: Shared Greedy Matching + Section Matching

**Files:**
- Create: `backend/app/matching.py`
- Create: `backend/app/section_matching.py`
- Test: `backend/tests/test_matching.py`
- Test: `backend/tests/test_section_matching.py`

**Interfaces:**
- Consumes: `app.embeddings.embed_texts`, `app.embeddings.cosine_similarity_matrix`, `app.models.Section`, `SectionMatch`, `SectionMatchResult`
- Produces: `app.matching.greedy_match(scores: numpy.ndarray, threshold: float) -> list[tuple[int, int, float]]` — reused by `move_reconciliation.py` (Task 7).
- Produces: `app.section_matching.match_sections(old_sections: list[Section], new_sections: list[Section], embed_fn=embed_texts, threshold: float = 0.5) -> SectionMatchResult` — used by `pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing test for `greedy_match`**

```python
# backend/tests/test_matching.py
import numpy as np

from app.matching import greedy_match


def test_greedy_match_picks_highest_scoring_pairs_first():
    scores = np.array([
        [0.9, 0.1],
        [0.2, 0.8],
    ])
    result = greedy_match(scores, threshold=0.5)
    assert sorted(result) == sorted([(0, 0, 0.9), (1, 1, 0.8)])


def test_greedy_match_excludes_pairs_below_threshold():
    scores = np.array([[0.3, 0.2]])
    result = greedy_match(scores, threshold=0.5)
    assert result == []


def test_greedy_match_does_not_reuse_a_row_or_column():
    scores = np.array([
        [0.95, 0.90],
        [0.85, 0.10],
    ])
    result = greedy_match(scores, threshold=0.5)
    # row 0 best match is col 0 (0.95); row 1's only remaining option is col 1 (0.10, below threshold)
    assert result == [(0, 0, 0.95)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.matching'`

- [ ] **Step 3: Write `backend/app/matching.py`**

```python
import numpy as np


def greedy_match(scores: np.ndarray, threshold: float) -> list[tuple[int, int, float]]:
    n_rows, n_cols = scores.shape
    candidates = [
        (float(scores[i][j]), i, j)
        for i in range(n_rows)
        for j in range(n_cols)
        if scores[i][j] >= threshold
    ]
    candidates.sort(key=lambda c: c[0], reverse=True)

    matched_rows: set[int] = set()
    matched_cols: set[int] = set()
    result: list[tuple[int, int, float]] = []
    for score, i, j in candidates:
        if i in matched_rows or j in matched_cols:
            continue
        result.append((i, j, score))
        matched_rows.add(i)
        matched_cols.add(j)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_matching.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing test for `match_sections`**

```python
# backend/tests/test_section_matching.py
import numpy as np

from app.models import Section, Paragraph
from app.section_matching import match_sections


def fake_embed_fn(texts: list[str]) -> np.ndarray:
    # Hand-crafted vectors: index position encodes "topic" so cosine similarity
    # is predictable without calling a real model.
    vector_by_text = {
        "Old A body a": np.array([1.0, 0.0, 0.0]),
        "Old B body b": np.array([0.0, 1.0, 0.0]),
        "New A body a": np.array([0.9, 0.1, 0.0]),
        "New C body c": np.array([0.0, 0.0, 1.0]),
    }
    return np.array([vector_by_text[t] for t in texts])


def test_match_sections_pairs_similar_sections_and_flags_the_rest():
    old_sections = [
        Section(heading="Old A", paragraphs=[Paragraph(text="body a")]),
        Section(heading="Old B", paragraphs=[Paragraph(text="body b")]),
    ]
    new_sections = [
        Section(heading="New A", paragraphs=[Paragraph(text="body a")]),
        Section(heading="New C", paragraphs=[Paragraph(text="body c")]),
    ]

    result = match_sections(old_sections, new_sections, embed_fn=fake_embed_fn, threshold=0.5)

    assert len(result.matches) == 1
    assert result.matches[0].old_index == 0
    assert result.matches[0].new_index == 0
    assert result.deleted_indices == [1]
    assert result.inserted_indices == [1]


def test_match_sections_handles_empty_input():
    result = match_sections([], [], embed_fn=fake_embed_fn, threshold=0.5)
    assert result.matches == []
    assert result.deleted_indices == []
    assert result.inserted_indices == []
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_section_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.section_matching'`

- [ ] **Step 7: Write `backend/app/section_matching.py`**

```python
from typing import Callable

import numpy as np

from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Section, SectionMatch, SectionMatchResult


def _section_text(section: Section) -> str:
    body = " ".join(p.text for p in section.paragraphs)
    return f"{section.heading} {body}".strip()


def match_sections(
    old_sections: list[Section],
    new_sections: list[Section],
    embed_fn: Callable[[list[str]], np.ndarray] = embed_texts,
    threshold: float = 0.5,
) -> SectionMatchResult:
    if not old_sections or not new_sections:
        return SectionMatchResult(
            matches=[],
            deleted_indices=list(range(len(old_sections))),
            inserted_indices=list(range(len(new_sections))),
        )

    old_texts = [_section_text(s) for s in old_sections]
    new_texts = [_section_text(s) for s in new_sections]
    scores = cosine_similarity_matrix(embed_fn(old_texts), embed_fn(new_texts))

    pairs = greedy_match(scores, threshold)
    matches = [SectionMatch(old_index=i, new_index=j, score=score) for i, j, score in pairs]

    matched_old = {m.old_index for m in matches}
    matched_new = {m.new_index for m in matches}
    deleted = [i for i in range(len(old_sections)) if i not in matched_old]
    inserted = [j for j in range(len(new_sections)) if j not in matched_new]
    return SectionMatchResult(matches=matches, deleted_indices=deleted, inserted_indices=inserted)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_section_matching.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Commit**

```bash
git add backend/app/matching.py backend/app/section_matching.py backend/tests/test_matching.py backend/tests/test_section_matching.py
git commit -m "feat: greedy score matching and embedding-based section matching"
```

---

### Task 6: Paragraph-Level Diffing

**Files:**
- Create: `backend/app/paragraph_diff.py`
- Test: `backend/tests/test_paragraph_diff.py`

**Interfaces:**
- Consumes: `app.models.Paragraph`
- Produces: `app.paragraph_diff.ParagraphOpcode` (dataclass: `tag: str`, `old_paragraphs: list[Paragraph]`, `new_paragraphs: list[Paragraph]`), `app.paragraph_diff.diff_paragraphs(old_paragraphs: list[Paragraph], new_paragraphs: list[Paragraph]) -> list[ParagraphOpcode]` — used by `pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_paragraph_diff.py
from app.models import Paragraph
from app.paragraph_diff import diff_paragraphs


def test_identical_paragraphs_are_equal():
    paras = [Paragraph(text="Same text.")]
    opcodes = diff_paragraphs(paras, paras)
    assert len(opcodes) == 1
    assert opcodes[0].tag == "equal"


def test_replaced_paragraph_is_tagged_replace():
    old = [Paragraph(text="Old wording.")]
    new = [Paragraph(text="New wording.")]
    opcodes = diff_paragraphs(old, new)
    assert len(opcodes) == 1
    assert opcodes[0].tag == "replace"
    assert opcodes[0].old_paragraphs == old
    assert opcodes[0].new_paragraphs == new


def test_added_and_deleted_paragraphs_are_tagged():
    old = [Paragraph(text="Stays the same.")]
    new = [Paragraph(text="Stays the same."), Paragraph(text="Brand new sentence.")]
    opcodes = diff_paragraphs(old, new)
    tags = [op.tag for op in opcodes]
    assert "equal" in tags
    assert "insert" in tags
    insert_op = next(op for op in opcodes if op.tag == "insert")
    assert insert_op.new_paragraphs[0].text == "Brand new sentence."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paragraph_diff.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.paragraph_diff'`

- [ ] **Step 3: Write `backend/app/paragraph_diff.py`**

```python
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models import Paragraph


@dataclass
class ParagraphOpcode:
    tag: str
    old_paragraphs: list[Paragraph]
    new_paragraphs: list[Paragraph]


def diff_paragraphs(old_paragraphs: list[Paragraph], new_paragraphs: list[Paragraph]) -> list[ParagraphOpcode]:
    old_texts = [p.text for p in old_paragraphs]
    new_texts = [p.text for p in new_paragraphs]
    matcher = SequenceMatcher(None, old_texts, new_texts)

    opcodes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        opcodes.append(
            ParagraphOpcode(
                tag=tag,
                old_paragraphs=old_paragraphs[i1:i2],
                new_paragraphs=new_paragraphs[j1:j2],
            )
        )
    return opcodes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paragraph_diff.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/paragraph_diff.py backend/tests/test_paragraph_diff.py
git commit -m "feat: difflib-based paragraph diffing within matched sections"
```

---

### Task 7: Move Reconciliation

**Files:**
- Create: `backend/app/move_reconciliation.py`
- Test: `backend/tests/test_move_reconciliation.py`

**Interfaces:**
- Consumes: `app.matching.greedy_match`, `app.embeddings.embed_texts`, `app.embeddings.cosine_similarity_matrix`, `app.models.Paragraph`, `MovedParagraph`
- Produces: `app.move_reconciliation.reconcile_moves(orphan_deletes: list[tuple[Paragraph, str]], orphan_inserts: list[tuple[Paragraph, str]], embed_fn=embed_texts, threshold: float = 0.85) -> tuple[list[MovedParagraph], list[tuple[Paragraph, str]], list[tuple[Paragraph, str]]]` (returns `moved, remaining_deletes, remaining_inserts`) — used by `pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_move_reconciliation.py
import numpy as np

from app.models import Paragraph
from app.move_reconciliation import reconcile_moves


def fake_embed_fn(texts: list[str]) -> np.ndarray:
    vector_by_text = {
        "The QA Manager shall sign the batch record.": np.array([1.0, 0.0]),
        "Unrelated deleted sentence.": np.array([0.0, 1.0]),
        "Unrelated inserted sentence.": np.array([0.0, 0.9]),
    }
    return np.array([vector_by_text[t] for t in texts])


def test_high_similarity_orphans_are_reclassified_as_moved():
    deletes = [(Paragraph(text="The QA Manager shall sign the batch record."), "3.0 Old Section")]
    inserts = [(Paragraph(text="The QA Manager shall sign the batch record."), "6.0 New Section")]

    moved, remaining_deletes, remaining_inserts = reconcile_moves(
        deletes, inserts, embed_fn=lambda texts: np.array([[1.0, 0.0]] * len(texts)), threshold=0.85
    )

    assert len(moved) == 1
    assert moved[0].old_section == "3.0 Old Section"
    assert moved[0].new_section == "6.0 New Section"
    assert remaining_deletes == []
    assert remaining_inserts == []


def test_low_similarity_orphans_stay_as_add_and_delete():
    deletes = [(Paragraph(text="Unrelated deleted sentence."), "2.0 Section")]
    inserts = [(Paragraph(text="Unrelated inserted sentence."), "5.0 Section")]

    moved, remaining_deletes, remaining_inserts = reconcile_moves(
        deletes, inserts, embed_fn=fake_embed_fn, threshold=0.999
    )

    assert moved == []
    assert remaining_deletes == deletes
    assert remaining_inserts == inserts


def test_empty_orphans_return_immediately():
    moved, remaining_deletes, remaining_inserts = reconcile_moves([], [], embed_fn=fake_embed_fn)
    assert moved == []
    assert remaining_deletes == []
    assert remaining_inserts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_move_reconciliation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.move_reconciliation'`

- [ ] **Step 3: Write `backend/app/move_reconciliation.py`**

```python
from typing import Callable

import numpy as np

from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Paragraph, MovedParagraph

Orphan = tuple[Paragraph, str]


def reconcile_moves(
    orphan_deletes: list[Orphan],
    orphan_inserts: list[Orphan],
    embed_fn: Callable[[list[str]], np.ndarray] = embed_texts,
    threshold: float = 0.85,
) -> tuple[list[MovedParagraph], list[Orphan], list[Orphan]]:
    if not orphan_deletes or not orphan_inserts:
        return [], orphan_deletes, orphan_inserts

    old_texts = [p.text for p, _ in orphan_deletes]
    new_texts = [p.text for p, _ in orphan_inserts]
    scores = cosine_similarity_matrix(embed_fn(old_texts), embed_fn(new_texts))

    pairs = greedy_match(scores, threshold)

    moved = []
    matched_old, matched_new = set(), set()
    for i, j, score in pairs:
        old_p, old_section = orphan_deletes[i]
        new_p, new_section = orphan_inserts[j]
        moved.append(
            MovedParagraph(
                old_paragraph=old_p, new_paragraph=new_p,
                old_section=old_section, new_section=new_section, score=score,
            )
        )
        matched_old.add(i)
        matched_new.add(j)

    remaining_deletes = [o for i, o in enumerate(orphan_deletes) if i not in matched_old]
    remaining_inserts = [o for j, o in enumerate(orphan_inserts) if j not in matched_new]
    return moved, remaining_deletes, remaining_inserts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_move_reconciliation.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/move_reconciliation.py backend/tests/test_move_reconciliation.py
git commit -m "feat: cross-document move reconciliation for orphaned paragraphs"
```

---

### Task 8: Regex Change Detectors & Risk Rules

**Files:**
- Create: `backend/app/regex_detectors.py`
- Create: `backend/app/risk_rules.py`
- Test: `backend/tests/test_regex_detectors.py`
- Test: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `app.models.RegexDetection`
- Produces: `app.regex_detectors.detect_regex_change(old_text: str, new_text: str) -> RegexDetection | None` — used by `pipeline.py` (Task 12).
- Produces: `app.risk_rules.RISK_TABLE: dict[str, str]`, `app.risk_rules.assign_risk(change_type: str) -> str` — used by `pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing regex tests**

```python
# backend/tests/test_regex_detectors.py
from app.regex_detectors import detect_regex_change


def test_numeric_change_when_only_numbers_differ():
    result = detect_regex_change(
        "Assay acceptance criterion: 95.0% to 105.0%.",
        "Assay acceptance criterion: 98.0% to 102.0%.",
    )
    assert result is not None
    assert result.change_type == "numeric_change"
    assert "95.0" in result.reason and "98.0" in result.reason


def test_unit_change_when_unit_token_differs():
    result = detect_regex_change("Weigh 10 mg of sample.", "Weigh 10 g of sample.")
    assert result is not None
    assert result.change_type == "unit_change"


def test_date_change_takes_priority_over_numeric():
    result = detect_regex_change(
        "Effective date: 01 Jan 2024.",
        "Effective date: 15 Mar 2024.",
    )
    assert result is not None
    assert result.change_type == "date_change"


def test_no_detection_when_text_has_no_numbers_units_or_dates():
    result = detect_regex_change(
        "The Quality Control Manager shall approve the result.",
        "The Quality Assurance Manager shall approve the result.",
    )
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_regex_detectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.regex_detectors'`

- [ ] **Step 3: Write `backend/app/regex_detectors.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_regex_detectors.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the failing risk rules test**

```python
# backend/tests/test_risk_rules.py
from app.risk_rules import assign_risk


def test_high_risk_change_types():
    for change_type in ["numeric_change", "unit_change", "process_sequence_change", "qualitative_specification_change"]:
        assert assign_risk(change_type) == "High"


def test_medium_risk_change_types():
    for change_type in ["role_responsibility_change", "reference_document_change", "date_change"]:
        assert assign_risk(change_type) == "Medium"


def test_low_risk_change_type():
    assert assign_risk("clarification_no_meaning_change") == "Low"


def test_informational_risk_change_type():
    assert assign_risk("formatting_only") == "Informational"


def test_structural_and_unknown_types_default_to_medium():
    for change_type in ["added_paragraph", "deleted_paragraph", "moved_paragraph", "unclassified", "something_new"]:
        assert assign_risk(change_type) == "Medium"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_risk_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.risk_rules'`

- [ ] **Step 7: Write `backend/app/risk_rules.py`**

```python
RISK_TABLE = {
    "numeric_change": "High",
    "unit_change": "High",
    "process_sequence_change": "High",
    "qualitative_specification_change": "High",
    "role_responsibility_change": "Medium",
    "reference_document_change": "Medium",
    "date_change": "Medium",
    "clarification_no_meaning_change": "Low",
    "formatting_only": "Informational",
}

DEFAULT_RISK = "Medium"


def assign_risk(change_type: str) -> str:
    return RISK_TABLE.get(change_type, DEFAULT_RISK)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_risk_rules.py -v`
Expected: PASS (5 tests)

- [ ] **Step 9: Commit**

```bash
git add backend/app/regex_detectors.py backend/app/risk_rules.py backend/tests/test_regex_detectors.py backend/tests/test_risk_rules.py
git commit -m "feat: regex-based numeric/unit/date detection and fixed risk rule table"
```

---

### Task 9: LLM Semantic Classifier (Gemini, Batched)

**Files:**
- Create: `backend/app/llm_classifier.py`
- Test: `backend/tests/test_llm_classifier.py`

**Interfaces:**
- Consumes: `app.config.GEMINI_API_KEY`, `app.config.GEMINI_MODEL`, `app.models.LLMClassification`
- Produces: `app.llm_classifier.classify_changes_batch(unresolved: list[dict]) -> list[LLMClassification]` where each item in `unresolved` is `{"change_id": str, "old_text": str, "new_text": str}` — used by `pipeline.py` (Task 12). Internally calls `app.llm_classifier._call_gemini(unresolved, model_name) -> str`, which is the only function that talks to the network — always mock this in tests.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_llm_classifier.py
import json

from app import llm_classifier
from app.llm_classifier import classify_changes_batch


def test_empty_input_returns_empty_list_without_calling_gemini(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("_call_gemini should not be called for empty input")

    monkeypatch.setattr(llm_classifier, "_call_gemini", fail_if_called)
    assert classify_changes_batch([]) == []


def test_parses_successful_gemini_response(monkeypatch):
    unresolved = [
        {"change_id": "c1", "old_text": "The QC Manager shall approve.", "new_text": "The QA Manager shall approve."},
    ]

    def fake_call_gemini(items, model_name):
        return json.dumps([
            {
                "change_id": "c1",
                "change_type": "role_responsibility_change",
                "reason": "Approval responsibility changed from QC Manager to QA Manager.",
                "confidence": 0.9,
            }
        ])

    monkeypatch.setattr(llm_classifier, "_call_gemini", fake_call_gemini)

    results = classify_changes_batch(unresolved)

    assert len(results) == 1
    assert results[0].change_id == "c1"
    assert results[0].change_type == "role_responsibility_change"
    assert results[0].confidence == 0.9


def test_gemini_failure_falls_back_to_unclassified(monkeypatch):
    unresolved = [
        {"change_id": "c1", "old_text": "a", "new_text": "b"},
        {"change_id": "c2", "old_text": "c", "new_text": "d"},
    ]

    def raise_error(items, model_name):
        raise RuntimeError("network error")

    monkeypatch.setattr(llm_classifier, "_call_gemini", raise_error)

    results = classify_changes_batch(unresolved)

    assert len(results) == 2
    assert all(r.change_type == "unclassified" for r in results)
    assert all(r.confidence == 0.0 for r in results)
    assert {r.change_id for r in results} == {"c1", "c2"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.llm_classifier'`

- [ ] **Step 3: Write `backend/app/llm_classifier.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_classifier.py -v`
Expected: PASS (3 tests) — no network call is made because `_call_gemini` is monkeypatched in every test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm_classifier.py backend/tests/test_llm_classifier.py
git commit -m "feat: batched Gemini classifier for semantic change types with safe fallback"
```

---

### Task 10: SQLite Persistence Layer

**Files:**
- Create: `backend/app/db.py`
- Create: `backend/app/repository.py`
- Test: `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: `app.models.Change`, `ComparisonResult`, `ComparisonSummary`, `build_summary`
- Produces: `app.db.get_connection(db_path: str) -> sqlite3.Connection`
- Produces: `app.repository.create_document(conn, filename: str, file_type: str, storage_path: str) -> str`, `get_document(conn, doc_id: str) -> dict | None`, `save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None`, `get_comparison(conn, comparison_id: str) -> ComparisonResult | None`, `update_change(conn, change_id: str, reviewer_risk_level=None, reviewer_comment=None, accepted=None) -> dict | None` — all used by `main.py` (Task 13).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_repository.py
from app.db import get_connection
from app.models import Change, ComparisonResult, build_summary
from app import repository


def make_conn():
    return get_connection(":memory:")


def test_create_and_get_document():
    conn = make_conn()
    doc_id = repository.create_document(conn, "sop_v1.pdf", "pdf", "/data/sop_v1.pdf")
    doc = repository.get_document(conn, doc_id)
    assert doc["filename"] == "sop_v1.pdf"
    assert doc["file_type"] == "pdf"
    assert doc["storage_path"] == "/data/sop_v1.pdf"


def test_get_document_returns_none_when_missing():
    conn = make_conn()
    assert repository.get_document(conn, "does-not-exist") is None


def test_save_and_get_comparison_round_trip():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")

    changes = [
        Change(
            change_id="ch-1", section="1.0 Scope", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-1", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-1")

    assert fetched is not None
    assert fetched.old_document == "old.txt"
    assert fetched.new_document == "new.txt"
    assert len(fetched.changes) == 1
    assert fetched.changes[0].change_type == "numeric_change"
    assert fetched.summary.high_risk == 1


def test_update_change_sets_reviewer_fields():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")
    changes = [
        Change(
            change_id="ch-1", section="1.0 Scope", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-1", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )
    repository.save_comparison(conn, comparison, old_id, new_id)

    updated = repository.update_change(conn, "ch-1", reviewer_risk_level="Low", accepted=True)
    assert updated["reviewer_risk_level"] == "Low"
    assert updated["accepted"] == 1

    fetched = repository.get_comparison(conn, "cmp-1")
    assert fetched.changes[0].reviewer_risk_level == "Low"
    assert fetched.changes[0].accepted is True


def test_update_change_returns_none_when_missing():
    conn = make_conn()
    assert repository.update_change(conn, "does-not-exist", accepted=True) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write `backend/app/db.py`**

```python
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY,
    old_document_id TEXT NOT NULL,
    new_document_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    section TEXT,
    change_type TEXT,
    old_text TEXT,
    new_text TEXT,
    old_page INTEGER,
    new_page INTEGER,
    confidence REAL,
    ai_risk_level TEXT,
    reviewer_risk_level TEXT,
    reason TEXT,
    reviewer_comment TEXT,
    accepted INTEGER DEFAULT 0
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
```

- [ ] **Step 4: Write `backend/app/repository.py`**

```python
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models import Change, ComparisonResult, build_summary


def create_document(conn, filename: str, file_type: str, storage_path: str) -> str:
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO documents (id, filename, file_type, storage_path, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, filename, file_type, storage_path, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return doc_id


def get_document(conn, doc_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None:
    conn.execute(
        "INSERT INTO comparisons (id, old_document_id, new_document_id, created_at) VALUES (?, ?, ?, ?)",
        (comparison.comparison_id, old_document_id, new_document_id, datetime.now(timezone.utc).isoformat()),
    )
    for c in comparison.changes:
        conn.execute(
            """INSERT INTO changes
               (id, comparison_id, section, change_type, old_text, new_text, old_page, new_page,
                confidence, ai_risk_level, reviewer_risk_level, reason, reviewer_comment, accepted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.change_id, comparison.comparison_id, c.section, c.change_type, c.old_text, c.new_text,
                c.old_page, c.new_page, c.confidence, c.ai_risk_level, c.reviewer_risk_level, c.reason,
                c.reviewer_comment, int(c.accepted),
            ),
        )
    conn.commit()


def _row_to_change(row) -> Change:
    return Change(
        change_id=row["id"], section=row["section"], change_type=row["change_type"],
        old_text=row["old_text"], new_text=row["new_text"], old_page=row["old_page"],
        new_page=row["new_page"], confidence=row["confidence"], ai_risk_level=row["ai_risk_level"],
        reason=row["reason"], reviewer_risk_level=row["reviewer_risk_level"],
        reviewer_comment=row["reviewer_comment"], accepted=bool(row["accepted"]),
    )


def get_comparison(conn, comparison_id: str) -> Optional[ComparisonResult]:
    comp_row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
    if not comp_row:
        return None
    old_doc = get_document(conn, comp_row["old_document_id"])
    new_doc = get_document(conn, comp_row["new_document_id"])
    change_rows = conn.execute("SELECT * FROM changes WHERE comparison_id = ?", (comparison_id,)).fetchall()
    changes = [_row_to_change(r) for r in change_rows]
    return ComparisonResult(
        comparison_id=comparison_id,
        old_document=old_doc["filename"] if old_doc else "",
        new_document=new_doc["filename"] if new_doc else "",
        summary=build_summary(changes),
        changes=changes,
    )


def update_change(
    conn,
    change_id: str,
    reviewer_risk_level: Optional[str] = None,
    reviewer_comment: Optional[str] = None,
    accepted: Optional[bool] = None,
) -> Optional[dict]:
    existing = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
    if not existing:
        return None

    fields, values = [], []
    if reviewer_risk_level is not None:
        fields.append("reviewer_risk_level = ?")
        values.append(reviewer_risk_level)
    if reviewer_comment is not None:
        fields.append("reviewer_comment = ?")
        values.append(reviewer_comment)
    if accepted is not None:
        fields.append("accepted = ?")
        values.append(int(accepted))

    if fields:
        values.append(change_id)
        conn.execute(f"UPDATE changes SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    updated = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
    return dict(updated)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_repository.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/app/repository.py backend/tests/test_repository.py
git commit -m "feat: SQLite schema and repository for documents, comparisons, and changes"
```

---

### Task 11: Report Export (JSON / CSV)

**Files:**
- Create: `backend/app/export.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `app.models.ComparisonResult`, `Change`
- Produces: `app.export.to_json(comparison: ComparisonResult) -> dict`, `app.export.to_csv(comparison: ComparisonResult) -> str` — used by `main.py` (Task 13).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_export.py
import csv
import io

from app.models import Change, ComparisonResult, build_summary
from app.export import to_json, to_csv


def make_comparison() -> ComparisonResult:
    changes = [
        Change(
            change_id="ch-1", section="Acceptance Criteria", change_type="numeric_change",
            old_text="Assay: 95.0% to 105.0%", new_text="Assay: 98.0% to 102.0%",
            old_page=4, new_page=5, confidence=0.97, ai_risk_level="High",
            reason="The approved assay acceptance range was narrowed.",
        ),
    ]
    return ComparisonResult(
        comparison_id="CMP-001", old_document="SOP_v1.pdf", new_document="SOP_v2.pdf",
        summary=build_summary(changes), changes=changes,
    )


def test_to_json_matches_expected_schema_shape():
    result = to_json(make_comparison())

    assert result["comparison_id"] == "CMP-001"
    assert result["old_document"] == "SOP_v1.pdf"
    assert result["new_document"] == "SOP_v2.pdf"
    assert result["summary"]["total_changes"] == 1
    assert result["summary"]["high_risk"] == 1

    change = result["changes"][0]
    assert change["change_id"] == "ch-1"
    assert change["change_type"] == "numeric_change"
    assert change["old_text"] == "Assay: 95.0% to 105.0%"
    assert change["new_text"] == "Assay: 98.0% to 102.0%"
    assert change["risk_level"] == "High"
    assert change["old_page"] == 4
    assert change["new_page"] == 5
    assert change["confidence"] == 0.97


def test_reviewer_override_takes_priority_in_risk_level():
    comparison = make_comparison()
    comparison.changes[0].reviewer_risk_level = "Low"
    result = to_json(comparison)
    assert result["changes"][0]["risk_level"] == "Low"
    assert result["changes"][0]["ai_risk_level"] == "High"


def test_to_csv_has_header_and_one_row_per_change():
    csv_text = to_csv(make_comparison())
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0][:3] == ["change_id", "section", "change_type"]
    assert len(rows) == 2
    assert rows[1][0] == "ch-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.export'`

- [ ] **Step 3: Write `backend/app/export.py`**

```python
import csv
import io

from app.models import ComparisonResult


def _effective_risk(change) -> str:
    return change.reviewer_risk_level or change.ai_risk_level


def to_json(comparison: ComparisonResult) -> dict:
    return {
        "comparison_id": comparison.comparison_id,
        "old_document": comparison.old_document,
        "new_document": comparison.new_document,
        "summary": {
            "total_changes": comparison.summary.total_changes,
            "high_risk": comparison.summary.high_risk,
            "medium_risk": comparison.summary.medium_risk,
            "low_risk": comparison.summary.low_risk,
            "informational": comparison.summary.informational,
        },
        "changes": [
            {
                "change_id": c.change_id,
                "section": c.section,
                "change_type": c.change_type,
                "old_text": c.old_text,
                "new_text": c.new_text,
                "risk_level": _effective_risk(c),
                "ai_risk_level": c.ai_risk_level,
                "reviewer_risk_level": c.reviewer_risk_level,
                "reason": c.reason,
                "old_page": c.old_page,
                "new_page": c.new_page,
                "confidence": c.confidence,
                "reviewer_comment": c.reviewer_comment,
                "accepted": c.accepted,
            }
            for c in comparison.changes
        ],
    }


def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
        ])
    return output.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/export.py backend/tests/test_export.py
git commit -m "feat: JSON and CSV export matching the outline's report schema"
```

---

### Task 12: Pipeline Orchestration (End-to-End Integration Test)

**Files:**
- Create: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `app.sectioning.split_into_sections`, `app.section_matching.match_sections`, `app.paragraph_diff.diff_paragraphs`, `app.move_reconciliation.reconcile_moves`, `app.regex_detectors.detect_regex_change`, `app.llm_classifier.classify_changes_batch`, `app.risk_rules.assign_risk`, `app.models.Paragraph`, `Change`, `ComparisonResult`, `build_summary`
- Produces: `app.pipeline.compare_documents(old_paragraphs: list[Paragraph], new_paragraphs: list[Paragraph], old_filename: str, new_filename: str) -> ComparisonResult` — used by `main.py` (Task 13).

**Note:** this test uses the real embedding model (no fake `embed_fn`) because it validates the full pipeline end-to-end, but mocks `llm_classifier.classify_changes_batch` so no live Gemini call happens.

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/test_pipeline.py
from app import pipeline, llm_classifier
from app.models import Paragraph, LLMClassification


def test_pipeline_reproduces_the_outline_example(monkeypatch):
    old_paragraphs = [
        Paragraph(text="Assay acceptance criterion: 95.0% to 105.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C."),
        Paragraph(text="The Quality Control Manager shall approve the result."),
    ]
    new_paragraphs = [
        Paragraph(text="Assay acceptance criterion: 98.0% to 102.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C and 60% RH ± 5% RH."),
        Paragraph(text="The Quality Assurance Manager shall approve the result."),
    ]

    def fake_classify(unresolved):
        return [
            LLMClassification(
                change_id=unresolved[0]["change_id"],
                change_type="role_responsibility_change",
                reason="Approval responsibility changed from QC Manager to QA Manager.",
                confidence=0.9,
            )
        ]

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    assert result.summary.total_changes == 3
    assert result.summary.high_risk == 2
    assert result.summary.medium_risk == 1

    change_types = {c.change_type for c in result.changes}
    assert "numeric_change" in change_types
    assert "unit_change" in change_types
    assert "role_responsibility_change" in change_types

    role_change = next(c for c in result.changes if c.change_type == "role_responsibility_change")
    assert role_change.ai_risk_level == "Medium"
    assert "QA Manager" in role_change.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Write `backend/app/pipeline.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (1 test) — downloads the embedding model on first run if not already cached.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: orchestrate the full comparison pipeline end-to-end"
```

---

### Task 13: FastAPI Endpoints

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `app.config`, `app.db.get_connection`, `app.repository.*`, `app.extraction.extract_text`, `app.pipeline.compare_documents`, `app.export.to_json`, `app.export.to_csv`
- Produces: `POST /documents`, `POST /compare`, `GET /comparisons/{comparison_id}`, `PATCH /changes/{change_id}`, `GET /comparisons/{comparison_id}/export` — used by the frontend `api_client.py` (Task 14).

- [ ] **Step 1: Write the failing API tests**

```python
# backend/tests/test_api.py
from fastapi.testclient import TestClient

from app import config, llm_classifier
from app.main import app
from app.models import LLMClassification

client = TestClient(app)


def setup_isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))


def fake_classify(unresolved):
    return [
        LLMClassification(
            change_id=item["change_id"], change_type="role_responsibility_change",
            reason="Approval responsibility changed.", confidence=0.9,
        )
        for item in unresolved
    ]


def test_upload_document_returns_id_and_extracted_text(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    response = client.post(
        "/documents",
        files={"file": ("old.txt", b"Assay acceptance criterion: 95.0% to 105.0%.", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "old.txt"
    assert body["extracted_text"] == ["Assay acceptance criterion: 95.0% to 105.0%."]
    assert "document_id" in body


def test_upload_rejects_unsupported_file_type(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    response = client.post("/documents", files={"file": ("old.xyz", b"data", "application/octet-stream")})
    assert response.status_code == 400


def test_compare_get_patch_and_export_flow(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    old_text = (
        b"Assay acceptance criterion: 95.0% to 105.0%.\n\n"
        b"Samples shall be stored at 25\xc2\xb0C \xc2\xb1 2\xc2\xb0C.\n\n"
        b"The Quality Control Manager shall approve the result."
    )
    new_text = (
        b"Assay acceptance criterion: 98.0% to 102.0%.\n\n"
        b"Samples shall be stored at 25\xc2\xb0C \xc2\xb1 2\xc2\xb0C and 60% RH \xc2\xb1 5% RH.\n\n"
        b"The Quality Assurance Manager shall approve the result."
    )

    old_resp = client.post("/documents", files={"file": ("old.txt", old_text, "text/plain")})
    new_resp = client.post("/documents", files={"file": ("new.txt", new_text, "text/plain")})

    compare_resp = client.post("/compare", json={
        "old_document_id": old_resp.json()["document_id"],
        "new_document_id": new_resp.json()["document_id"],
    })
    assert compare_resp.status_code == 200
    comparison = compare_resp.json()
    assert comparison["summary"]["total_changes"] == 3
    comparison_id = comparison["comparison_id"]

    get_resp = client.get(f"/comparisons/{comparison_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["summary"]["total_changes"] == 3

    change_id = comparison["changes"][0]["change_id"]
    patch_resp = client.patch(f"/changes/{change_id}", json={"reviewer_risk_level": "Low", "accepted": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["reviewer_risk_level"] == "Low"

    export_resp = client.get(f"/comparisons/{comparison_id}/export", params={"format": "csv"})
    assert export_resp.status_code == 200
    assert "change_id" in export_resp.text


def test_compare_returns_404_for_unknown_document(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    response = client.post("/compare", json={"old_document_id": "missing-1", "new_document_id": "missing-2"})
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL — `/documents`, `/compare`, etc. don't exist yet (404s where 200s are expected).

- [ ] **Step 3: Modify `backend/app/main.py`**

```python
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import config, db, repository, extraction, pipeline, export

app = FastAPI(title="Pharma Document Change Analyzer")

SUPPORTED_TYPES = {"pdf", "docx", "txt"}


def _get_conn():
    return db.get_connection(config.DB_PATH)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/documents")
async def upload_document(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_name = f"{uuid.uuid4()}_{file.filename}"
    storage_path = str(upload_dir / temp_name)
    with open(storage_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    conn = _get_conn()
    document_id = repository.create_document(conn, file.filename, suffix, storage_path)
    paragraphs = extraction.extract_text(storage_path, suffix)

    return {
        "document_id": document_id,
        "filename": file.filename,
        "extracted_text": [p.text for p in paragraphs],
    }


class ComparePayload(BaseModel):
    old_document_id: str
    new_document_id: str


@app.post("/compare")
def compare(payload: ComparePayload):
    conn = _get_conn()
    old_doc = repository.get_document(conn, payload.old_document_id)
    new_doc = repository.get_document(conn, payload.new_document_id)
    if not old_doc or not new_doc:
        raise HTTPException(status_code=404, detail="Document not found")

    old_paragraphs = extraction.extract_text(old_doc["storage_path"], old_doc["file_type"])
    new_paragraphs = extraction.extract_text(new_doc["storage_path"], new_doc["file_type"])

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, old_doc["filename"], new_doc["filename"])
    repository.save_comparison(conn, result, payload.old_document_id, payload.new_document_id)
    return export.to_json(result)


@app.get("/comparisons/{comparison_id}")
def get_comparison_endpoint(comparison_id: str):
    conn = _get_conn()
    result = repository.get_comparison(conn, comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return export.to_json(result)


class ChangeUpdate(BaseModel):
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: Optional[bool] = None


@app.patch("/changes/{change_id}")
def patch_change(change_id: str, payload: ChangeUpdate):
    conn = _get_conn()
    updated = repository.update_change(
        conn, change_id,
        reviewer_risk_level=payload.reviewer_risk_level,
        reviewer_comment=payload.reviewer_comment,
        accepted=payload.accepted,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Change not found")
    return updated


@app.get("/comparisons/{comparison_id}/export")
def export_comparison(comparison_id: str, format: str = "json"):
    conn = _get_conn()
    result = repository.get_comparison(conn, comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    if format == "csv":
        return PlainTextResponse(export.to_csv(result), media_type="text/csv")
    return export.to_json(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest -v`
Expected: PASS (all tests across every module)

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "feat: wire up document upload, compare, fetch, review, and export endpoints"
```

---

### Task 14: Frontend Scaffold — API Client

**Files:**
- Create: `frontend/requirements.txt`
- Create: `frontend/pytest.ini`
- Create: `frontend/api_client.py`
- Test: `frontend/tests/test_api_client.py`

**Interfaces:**
- Produces: `api_client.API_BASE_URL: str`, `api_client.upload_document(file_name: str, file_bytes: bytes) -> dict`, `api_client.compare_documents(old_document_id: str, new_document_id: str) -> dict`, `api_client.get_comparison(comparison_id: str) -> dict`, `api_client.update_change(change_id: str, **fields) -> dict`, `api_client.export_comparison(comparison_id: str, fmt: str) -> bytes` — used by every Streamlit page (Tasks 15-18).

- [ ] **Step 1: Write `frontend/requirements.txt`**

```
streamlit==1.38.0
requests==2.32.3
pytest==8.3.3
```

- [ ] **Step 2: Write `frontend/pytest.ini`**

```ini
[pytest]
pythonpath = .
```

- [ ] **Step 3: Write the failing tests**

```python
# frontend/tests/test_api_client.py
from unittest.mock import patch, Mock

import api_client


def test_upload_document_posts_file_and_returns_json():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"document_id": "doc-1", "filename": "old.txt", "extracted_text": ["a"]}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.post", return_value=fake_response) as mock_post:
        result = api_client.upload_document("old.txt", b"content")

    assert result["document_id"] == "doc-1"
    args, kwargs = mock_post.call_args
    assert args[0] == f"{api_client.API_BASE_URL}/documents"
    assert kwargs["files"]["file"][0] == "old.txt"


def test_compare_documents_posts_ids_as_json():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"comparison_id": "cmp-1", "summary": {"total_changes": 3}}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.post", return_value=fake_response) as mock_post:
        result = api_client.compare_documents("old-id", "new-id")

    assert result["comparison_id"] == "cmp-1"
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"old_document_id": "old-id", "new_document_id": "new-id"}


def test_get_comparison_calls_expected_url():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"comparison_id": "cmp-1"}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.get", return_value=fake_response) as mock_get:
        api_client.get_comparison("cmp-1")

    mock_get.assert_called_once_with(f"{api_client.API_BASE_URL}/comparisons/cmp-1")


def test_update_change_sends_patch_with_given_fields():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"reviewer_risk_level": "Low"}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.patch", return_value=fake_response) as mock_patch:
        api_client.update_change("ch-1", reviewer_risk_level="Low", accepted=True)

    args, kwargs = mock_patch.call_args
    assert args[0] == f"{api_client.API_BASE_URL}/changes/ch-1"
    assert kwargs["json"] == {"reviewer_risk_level": "Low", "accepted": True}


def test_export_comparison_returns_raw_bytes():
    fake_response = Mock(status_code=200, content=b"csv,data")
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.get", return_value=fake_response) as mock_get:
        result = api_client.export_comparison("cmp-1", "csv")

    assert result == b"csv,data"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"format": "csv"}
```

- [ ] **Step 4: Run tests to verify they fail**

Run (from `frontend/`): `pytest tests/test_api_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api_client'`

- [ ] **Step 5: Write `frontend/api_client.py`**

```python
import os

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def upload_document(file_name: str, file_bytes: bytes) -> dict:
    response = requests.post(
        f"{API_BASE_URL}/documents",
        files={"file": (file_name, file_bytes)},
    )
    response.raise_for_status()
    return response.json()


def compare_documents(old_document_id: str, new_document_id: str) -> dict:
    response = requests.post(
        f"{API_BASE_URL}/compare",
        json={"old_document_id": old_document_id, "new_document_id": new_document_id},
    )
    response.raise_for_status()
    return response.json()


def get_comparison(comparison_id: str) -> dict:
    response = requests.get(f"{API_BASE_URL}/comparisons/{comparison_id}")
    response.raise_for_status()
    return response.json()


def update_change(change_id: str, **fields) -> dict:
    response = requests.patch(f"{API_BASE_URL}/changes/{change_id}", json=fields)
    response.raise_for_status()
    return response.json()


def export_comparison(comparison_id: str, fmt: str) -> bytes:
    response = requests.get(
        f"{API_BASE_URL}/comparisons/{comparison_id}/export",
        params={"format": fmt},
    )
    response.raise_for_status()
    return response.content
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_api_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/requirements.txt frontend/pytest.ini frontend/api_client.py frontend/tests/test_api_client.py
git commit -m "feat: frontend scaffold with a typed API client"
```

---

### Task 15: Streamlit Page 1 — Upload & Compare

**Files:**
- Create: `frontend/Home.py`
- Create: `frontend/pages/1_Upload_and_Compare.py`
- Test: `frontend/tests/test_page_upload_and_compare.py`

**Interfaces:**
- Consumes: `api_client.upload_document`, `api_client.compare_documents`
- Produces: `st.session_state["old_document"]`, `st.session_state["new_document"]`, `st.session_state["comparison"]`, `st.session_state["comparison_id"]` — consumed by Pages 2-4 (Tasks 16-18).

- [ ] **Step 1: Write `frontend/Home.py`**

```python
import streamlit as st

st.set_page_config(page_title="Pharma Document Change Analyzer")
st.title("Pharma Document Change Analyzer")
st.write("Use the pages in the sidebar to upload documents, compare them, and review changes.")
```

- [ ] **Step 2: Write the failing smoke test**

```python
# frontend/tests/test_page_upload_and_compare.py
from streamlit.testing.v1 import AppTest


def test_page_loads_without_error_when_nothing_uploaded_yet():
    at = AppTest.from_file("pages/1_Upload_and_Compare.py")
    at.run()
    assert not at.exception
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `frontend/`): `pytest tests/test_page_upload_and_compare.py -v`
Expected: FAIL — the page file doesn't exist yet.

- [ ] **Step 4: Write `frontend/pages/1_Upload_and_Compare.py`**

```python
import streamlit as st

from api_client import upload_document, compare_documents

st.title("Upload & Compare")

old_file = st.file_uploader("Previous document", type=["pdf", "docx", "txt"], key="old_file")
new_file = st.file_uploader("Revised document", type=["pdf", "docx", "txt"], key="new_file")

if old_file is not None and st.session_state.get("old_filename") != old_file.name:
    st.session_state["old_document"] = upload_document(old_file.name, old_file.getvalue())
    st.session_state["old_filename"] = old_file.name

if new_file is not None and st.session_state.get("new_filename") != new_file.name:
    st.session_state["new_document"] = upload_document(new_file.name, new_file.getvalue())
    st.session_state["new_filename"] = new_file.name

if st.session_state.get("old_document"):
    st.subheader(f"Previous: {st.session_state['old_document']['filename']}")
    st.text_area(
        "Extracted text (previous)",
        "\n\n".join(st.session_state["old_document"]["extracted_text"]),
        height=200,
    )

if st.session_state.get("new_document"):
    st.subheader(f"Revised: {st.session_state['new_document']['filename']}")
    st.text_area(
        "Extracted text (revised)",
        "\n\n".join(st.session_state["new_document"]["extracted_text"]),
        height=200,
    )

if st.session_state.get("old_document") and st.session_state.get("new_document"):
    if st.button("Compare"):
        with st.spinner("Comparing documents..."):
            comparison = compare_documents(
                st.session_state["old_document"]["document_id"],
                st.session_state["new_document"]["document_id"],
            )
        st.session_state["comparison"] = comparison
        st.session_state["comparison_id"] = comparison["comparison_id"]
        st.success(f"Comparison complete: {comparison['summary']['total_changes']} changes found.")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_page_upload_and_compare.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add frontend/Home.py "frontend/pages/1_Upload_and_Compare.py" frontend/tests/test_page_upload_and_compare.py
git commit -m "feat: Upload & Compare page"
```

---

### Task 16: Streamlit Page 2 — Change Summary

**Files:**
- Create: `frontend/pages/2_Change_Summary.py`
- Test: `frontend/tests/test_page_change_summary.py`

**Interfaces:**
- Consumes: `st.session_state["comparison"]`

- [ ] **Step 1: Write the failing smoke test**

```python
# frontend/tests/test_page_change_summary.py
from streamlit.testing.v1 import AppTest


def test_page_prompts_for_a_comparison_when_none_exists():
    at = AppTest.from_file("pages/2_Change_Summary.py")
    at.run()
    assert not at.exception


def test_page_shows_metrics_when_a_comparison_exists():
    at = AppTest.from_file("pages/2_Change_Summary.py")
    at.session_state["comparison"] = {
        "summary": {"total_changes": 3, "high_risk": 2, "medium_risk": 1, "low_risk": 0, "informational": 0}
    }
    at.run()
    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert "3" in metric_values
    assert "2" in metric_values
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_page_change_summary.py -v`
Expected: FAIL — the page file doesn't exist yet.

- [ ] **Step 3: Write `frontend/pages/2_Change_Summary.py`**

```python
import streamlit as st

st.title("Change Summary")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    summary = comparison["summary"]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Changes", summary["total_changes"])
    col2.metric("High Risk", summary["high_risk"])
    col3.metric("Medium Risk", summary["medium_risk"])
    col4.metric("Low Risk", summary["low_risk"])
    col5.metric("Informational", summary["informational"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_page_change_summary.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add "frontend/pages/2_Change_Summary.py" frontend/tests/test_page_change_summary.py
git commit -m "feat: Change Summary page"
```

---

### Task 17: Streamlit Page 3 — Detailed Changes (with Filtering Logic)

**Files:**
- Create: `frontend/logic.py`
- Create: `frontend/pages/3_Detailed_Changes.py`
- Test: `frontend/tests/test_logic.py`
- Test: `frontend/tests/test_page_detailed_changes.py`

**Interfaces:**
- Produces: `logic.filter_changes(changes: list[dict], risk: str | None, section: str | None, change_type: str | None) -> list[dict]` — reused by Page 4 (Task 18) for building the editable table.

- [ ] **Step 1: Write the failing logic test**

```python
# frontend/tests/test_logic.py
from logic import filter_changes

CHANGES = [
    {"change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change", "ai_risk_level": "High", "reviewer_risk_level": None},
    {"change_id": "2", "section": "Storage Conditions", "change_type": "unit_change", "ai_risk_level": "High", "reviewer_risk_level": None},
    {"change_id": "3", "section": "Responsibilities", "change_type": "role_responsibility_change", "ai_risk_level": "Medium", "reviewer_risk_level": "Low"},
]


def test_no_filters_returns_all_changes():
    assert filter_changes(CHANGES, None, None, None) == CHANGES


def test_filter_by_risk_uses_reviewer_override_when_present():
    result = filter_changes(CHANGES, "Low", None, None)
    assert [c["change_id"] for c in result] == ["3"]


def test_filter_by_section():
    result = filter_changes(CHANGES, None, "Storage Conditions", None)
    assert [c["change_id"] for c in result] == ["2"]


def test_filter_by_change_type():
    result = filter_changes(CHANGES, None, None, "numeric_change")
    assert [c["change_id"] for c in result] == ["1"]


def test_combined_filters():
    result = filter_changes(CHANGES, "High", "Storage Conditions", "unit_change")
    assert [c["change_id"] for c in result] == ["2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'logic'`

- [ ] **Step 3: Write `frontend/logic.py`**

```python
def filter_changes(
    changes: list[dict],
    risk: str | None,
    section: str | None,
    change_type: str | None,
) -> list[dict]:
    result = changes
    if risk:
        result = [c for c in result if (c.get("reviewer_risk_level") or c["ai_risk_level"]) == risk]
    if section:
        result = [c for c in result if c["section"] == section]
    if change_type:
        result = [c for c in result if c["change_type"] == change_type]
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_logic.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the failing page smoke test**

```python
# frontend/tests/test_page_detailed_changes.py
from streamlit.testing.v1 import AppTest


def test_page_loads_with_no_comparison():
    at = AppTest.from_file("pages/3_Detailed_Changes.py")
    at.run()
    assert not at.exception


def test_page_loads_with_a_comparison():
    at = AppTest.from_file("pages/3_Detailed_Changes.py")
    at.session_state["comparison"] = {
        "changes": [
            {
                "change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change",
                "old_text": "95%", "new_text": "98%", "ai_risk_level": "High",
                "reviewer_risk_level": None, "reason": "narrowed",
            },
        ]
    }
    at.run()
    assert not at.exception
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_page_detailed_changes.py -v`
Expected: FAIL — the page file doesn't exist yet.

- [ ] **Step 7: Write `frontend/pages/3_Detailed_Changes.py`**

```python
import streamlit as st

from logic import filter_changes

st.title("Detailed Changes")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    changes = comparison["changes"]
    sections = sorted({c["section"] for c in changes})
    change_types = sorted({c["change_type"] for c in changes})

    risk_filter = st.selectbox("Filter by risk", ["All", "High", "Medium", "Low", "Informational"])
    section_filter = st.selectbox("Filter by section", ["All"] + sections)
    type_filter = st.selectbox("Filter by change type", ["All"] + change_types)

    filtered = filter_changes(
        changes,
        risk=None if risk_filter == "All" else risk_filter,
        section=None if section_filter == "All" else section_filter,
        change_type=None if type_filter == "All" else type_filter,
    )

    st.table([
        {
            "Section": c["section"],
            "Old Text": c["old_text"],
            "New Text": c["new_text"],
            "Change Type": c["change_type"],
            "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "Reason": c["reason"],
        }
        for c in filtered
    ])
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_page_detailed_changes.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Commit**

```bash
git add frontend/logic.py "frontend/pages/3_Detailed_Changes.py" frontend/tests/test_logic.py frontend/tests/test_page_detailed_changes.py
git commit -m "feat: Detailed Changes page with risk/section/type filtering"
```

---

### Task 18: Streamlit Page 4 — Review & Export

**Files:**
- Modify: `frontend/logic.py`
- Create: `frontend/pages/4_Review_and_Export.py`
- Test: `frontend/tests/test_logic.py`
- Test: `frontend/tests/test_page_review_and_export.py`

**Interfaces:**
- Consumes: `logic.filter_changes`, `api_client.update_change`, `api_client.export_comparison`
- Produces: `logic.build_change_update_payload(edited_row: dict, original_row: dict) -> dict`

- [ ] **Step 1: Add the failing test for the payload-diff helper**

```python
# frontend/tests/test_logic.py (append to the existing file)
from logic import build_change_update_payload


def test_build_change_update_payload_includes_only_changed_fields():
    original = {"reviewer_risk_level": None, "reviewer_comment": None, "accepted": False}
    edited = {"reviewer_risk_level": "Low", "reviewer_comment": None, "accepted": True}

    payload = build_change_update_payload(edited, original)

    assert payload == {"reviewer_risk_level": "Low", "accepted": True}


def test_build_change_update_payload_is_empty_when_nothing_changed():
    row = {"reviewer_risk_level": "Low", "reviewer_comment": "ok", "accepted": True}
    assert build_change_update_payload(row, row) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_logic.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_change_update_payload'`

- [ ] **Step 3: Add to `frontend/logic.py`**

```python
def build_change_update_payload(edited_row: dict, original_row: dict) -> dict:
    payload = {}
    for field in ("reviewer_risk_level", "reviewer_comment", "accepted"):
        if edited_row.get(field) != original_row.get(field):
            payload[field] = edited_row.get(field)
    return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_logic.py -v`
Expected: PASS (7 tests total in this file)

- [ ] **Step 5: Write the failing page smoke test**

```python
# frontend/tests/test_page_review_and_export.py
from streamlit.testing.v1 import AppTest


def test_page_loads_with_no_comparison():
    at = AppTest.from_file("pages/4_Review_and_Export.py")
    at.run()
    assert not at.exception


def test_page_loads_with_a_comparison():
    at = AppTest.from_file("pages/4_Review_and_Export.py")
    at.session_state["comparison"] = {
        "comparison_id": "cmp-1",
        "changes": [
            {
                "change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change",
                "old_text": "95%", "new_text": "98%", "ai_risk_level": "High",
                "reviewer_risk_level": None, "reviewer_comment": None, "accepted": False,
                "reason": "narrowed",
            },
        ],
    }
    at.run()
    assert not at.exception
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_page_review_and_export.py -v`
Expected: FAIL — the page file doesn't exist yet.

- [ ] **Step 7: Write `frontend/pages/4_Review_and_Export.py`**

```python
import streamlit as st

from api_client import update_change, export_comparison
from logic import build_change_update_payload

st.title("Review & Export")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    changes_by_id = {c["change_id"]: c for c in comparison["changes"]}

    editable_rows = [
        {
            "change_id": c["change_id"],
            "section": c["section"],
            "reason": c["reason"],
            "reviewer_risk_level": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "reviewer_comment": c.get("reviewer_comment") or "",
            "accepted": c.get("accepted", False),
        }
        for c in comparison["changes"]
    ]

    edited_rows = st.data_editor(
        editable_rows,
        column_config={
            "reviewer_risk_level": st.column_config.SelectboxColumn(
                options=["High", "Medium", "Low", "Informational"]
            ),
        },
        disabled=["change_id", "section", "reason"],
        hide_index=True,
        key="review_editor",
    )

    if st.button("Save reviewer edits"):
        for edited in edited_rows:
            original = changes_by_id[edited["change_id"]]
            original_row = {
                "reviewer_risk_level": original.get("reviewer_risk_level"),
                "reviewer_comment": original.get("reviewer_comment"),
                "accepted": original.get("accepted", False),
            }
            payload = build_change_update_payload(edited, original_row)
            if payload:
                update_change(edited["change_id"], **payload)
        st.success("Reviewer edits saved.")

    st.divider()
    st.subheader("Export")
    export_format = st.radio("Format", ["json", "csv"], horizontal=True)
    if st.button("Download report"):
        content = export_comparison(comparison["comparison_id"], export_format)
        st.download_button(
            "Save file",
            data=content,
            file_name=f"comparison_{comparison['comparison_id']}.{export_format}",
        )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_page_review_and_export.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Run the full frontend test suite**

Run: `pytest -v`
Expected: PASS (all tests across every module)

- [ ] **Step 10: Commit**

```bash
git add frontend/logic.py "frontend/pages/4_Review_and_Export.py" frontend/tests/test_logic.py frontend/tests/test_page_review_and_export.py
git commit -m "feat: Review & Export page with reviewer edits and CSV/JSON download"
```

---

### Task 19: Docker Compose Wiring & Run Instructions

**Files:**
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `README.md`

**Interfaces:**
- Consumes: `backend/Dockerfile` (Task 1), `frontend/requirements.txt` (Task 14)

- [ ] **Step 1: Write `frontend/Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "Home.py", "--server.address=0.0.0.0", "--server.port=8501"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  api:
    build: ./backend
    volumes:
      - data:/data
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - DB_PATH=/data/app.db
      - UPLOAD_DIR=/data/uploads
    ports:
      - "8000:8000"

  ui:
    build: ./frontend
    environment:
      - API_BASE_URL=http://api:8000
    ports:
      - "8501:8501"
    depends_on:
      - api

volumes:
  data:
```

- [ ] **Step 3: Write `.env.example`**

```
GEMINI_API_KEY=your-gemini-api-key-here
```

- [ ] **Step 4: Write `.gitignore`**

```
.env
__pycache__/
*.pyc
*.db
.venv/
uploads/
```

- [ ] **Step 5: Write `README.md`**

```markdown
# Pharma Document Change Analyzer

Compares two versions of a pharmaceutical document and produces a categorized,
risk-scored change report.

## Run locally with Docker Compose

1. Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY`.
2. `docker compose up --build`
3. Open the UI at http://localhost:8501 (the API is at http://localhost:8000).

## Run tests without Docker

Backend: `cd backend && pip install -r requirements.txt && pytest -v`
Frontend: `cd frontend && pip install -r requirements.txt && pytest -v`
```

- [ ] **Step 6: Validate the Compose file**

Run: `docker compose config`
Expected: prints the fully resolved configuration with no errors.

- [ ] **Step 7: Build both images**

Run: `docker compose build`
Expected: both `api` and `ui` images build successfully (the `api` build takes longer on first run while it downloads the embedding model).

- [ ] **Step 8: Start the stack and smoke-test it**

Run: `docker compose up -d`
Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

Open `http://localhost:8501` in a browser and confirm the "Upload & Compare" page loads.

- [ ] **Step 9: Stop the stack**

Run: `docker compose down`

- [ ] **Step 10: Commit**

```bash
git add frontend/Dockerfile docker-compose.yml .env.example .gitignore README.md
git commit -m "feat: Docker Compose wiring for the api and ui services"
```
