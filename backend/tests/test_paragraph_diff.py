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
