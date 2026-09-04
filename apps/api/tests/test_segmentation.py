from __future__ import annotations

from itertools import pairwise

from app.schemas import SegmentKind
from app.services.optimizer.segmentation import segment


def kinds(text: str) -> set[SegmentKind]:
    return {s.kind for s in segment(text)}


def test_spans_are_contiguous_and_cover_the_whole_text():
    text = "Hello  world\n\n```py\nx  =  1\n```\n\nBye https://example.com/a?b=1"
    spans = segment(text)
    assert spans[0].start == 0
    assert spans[-1].end == len(text)
    for a, b in pairwise(spans):
        assert a.end == b.start, "segments must tile the text with no gaps or overlaps"


def test_fenced_code_is_detected_and_isolated():
    text = "before\n\n```python\ndef f():\n    return  1\n```\n\nafter"
    spans = segment(text)
    code = [s for s in spans if s.kind is SegmentKind.FENCED_CODE]
    assert len(code) == 1
    assert "def f():" in text[code[0].start : code[0].end]


def test_json_block_detected_by_real_parser():
    text = 'Here is data:\n{\n  "name": "Ada",\n  "age": 36\n}\nEnd.'
    spans = segment(text)
    blocks = [s for s in spans if s.kind is SegmentKind.JSON_BLOCK]
    assert len(blocks) == 1
    import json

    assert json.loads(text[blocks[0].start : blocks[0].end])["name"] == "Ada"


def test_brace_soup_is_not_mistaken_for_json():
    # A regex brace-matcher would claim this; the real parser must not.
    text = "Use the {placeholder} and then { not json at all here honestly }"
    assert SegmentKind.JSON_BLOCK not in kinds(text)


def test_template_vars_and_urls_are_protected():
    text = "Call {{user_name}} at https://api.example.com/v1/thing?x=1 now"
    found = kinds(text)
    assert SegmentKind.TEMPLATE_VAR in found
    assert SegmentKind.URL in found


def test_markdown_table_detected():
    text = "intro\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\nafter"
    assert SegmentKind.MARKDOWN_TABLE in kinds(text)


def test_json_scan_is_bounded_on_adversarial_input():
    # 50k opening braces must not cause quadratic parsing.
    text = "{" * 50_000
    spans = segment(text)
    assert spans  # completes, and does so quickly
