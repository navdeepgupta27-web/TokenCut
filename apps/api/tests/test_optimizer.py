"""Optimizer guarantees.

These are the tests the design doc calls non-negotiable: JSON equivalence,
protected regions, and the invariant that no rule ever increases token count.
"""

from __future__ import annotations

import json

import pytest

from app.schemas import Profile
from app.services.optimizer.pipeline import ALL_RULES, run_pipeline
from app.services.optimizer.rules import Edit, apply_edits, resolve_overlaps

CORPUS: list[str] = [
    "Please  summarize   the following  text.\r\n\r\n\r\nThank you!",
    'Data: [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}]',
    "```python\ndef f( ):\n    return  '  keep   me  '\n```",
    "Use {{template_var}}   and   ${other}  carefully and thoroughly and precisely.",
    "You are a helpful assistant.\n\nYou are a careful assistant.\n\nDo the thing.",
    "- Do not use markdown\n- Do not use markdown\n- Never apologise",
    "Mixed “smart quotes” — with an em dash… and nbsp.",
    "| a | b |\n| --- | --- |\n| 1 | 2 |",
    "https://example.com/very/long/path?with=query&params=1",
    "",
    "   ",
    "x" * 5000,
]


@pytest.mark.parametrize("text", CORPUS)
@pytest.mark.parametrize("profile", list(Profile))
def test_no_rule_ever_increases_token_count(text: str, profile: Profile):
    out = run_pipeline(text, profile=profile)
    assert out.tokens_after <= out.tokens_before, (
        f"profile={profile} increased tokens: "
        f"{out.tokens_before} -> {out.tokens_after}"
    )


@pytest.mark.parametrize("text", CORPUS)
def test_applied_savings_never_exceed_the_measured_total(text: str):
    out = run_pipeline(text, profile=Profile.BALANCED)
    total = out.tokens_before - out.tokens_after
    assert sum(a.tokens_saved for a in out.applied) <= max(0, total)


def test_compact_json_preserves_parsed_value():
    payload = {"b": 2, "a": [1, 2, {"deep": True}], "s": "keep  spaces"}
    text = "Context:\n" + json.dumps(payload, indent=4) + "\nEnd."
    out = run_pipeline(text, profile=Profile.BALANCED)

    assert out.tokens_after < out.tokens_before
    # The JSON in the optimized text must parse to exactly the same value.
    start = out.optimized_text.index("{")
    end = out.optimized_text.rindex("}") + 1
    assert json.loads(out.optimized_text[start:end]) == payload


def test_json_array_becomes_markdown_table_and_keeps_every_field():
    rows = [
        {"id": 1, "name": "Ada", "role": "engineer"},
        {"id": 2, "name": "Grace", "role": "admiral"},
        {"id": 3, "name": "Katherine", "role": "mathematician"},
    ]
    text = "Records:\n" + json.dumps(rows, indent=2)
    out = run_pipeline(text, profile=Profile.BALANCED)

    assert "| id | name | role |" in out.optimized_text
    for row in rows:
        for value in row.values():
            assert str(value) in out.optimized_text
    assert out.tokens_after < out.tokens_before


def test_ragged_json_array_is_not_tabled():
    rows = [{"a": 1, "b": 2}, {"a": 3}]  # missing key — tabling would drop data
    text = json.dumps(rows, indent=2)
    out = run_pipeline(text, profile=Profile.BALANCED)
    assert "| a | b |" not in out.optimized_text


def test_nested_json_array_is_not_tabled():
    rows = [{"a": {"deep": 1}}, {"a": {"deep": 2}}]
    text = json.dumps(rows, indent=2)
    out = run_pipeline(text, profile=Profile.BALANCED)
    assert "| a |" not in out.optimized_text


def test_code_blocks_are_never_modified():
    code = "```python\ndef f( ):\n    s = '  three   spaces  '\n    return   s\n```"
    text = f"Please  clean   this up.\n\n{code}\n\nThank  you."
    out = run_pipeline(text, profile=Profile.AGGRESSIVE)
    assert code in out.optimized_text, "whitespace rules leaked into a code fence"


def test_template_variables_survive():
    text = "Greet   {{user_name}}  using  ${greeting}   politely."
    out = run_pipeline(text, profile=Profile.AGGRESSIVE)
    assert "{{user_name}}" in out.optimized_text
    assert "${greeting}" in out.optimized_text


def test_urls_are_not_touched():
    url = "https://example.com/a/b?c=1&d=2"
    out = run_pipeline(f"See  {url}   for  details.", profile=Profile.AGGRESSIVE)
    assert url in out.optimized_text


# -- span-boundary regressions ---------------------------------------------
#
# The protected-region design guarantees no protected BYTE is modified. It said
# nothing about the bytes immediately either side, and that gap was a real bug:
# `trim_trailing_whitespace` matched `[ \t]+\Z` against each span's substring,
# so `\Z` meant "end of this chunk" and the space before every protected region
# was deleted — "endpoint at  https://..." became "endpoint athttps://...".
#
# Fixed by matching the whole document and filtering by span. These tests pin
# the boundaries, not just the interiors.


@pytest.mark.parametrize(
    "protected",
    [
        "https://api.example.com/v1/thing?strict=true",
        "{{user_name}}",
        "${greeting}",
        "`inline_code()`",
        "someone@example.com",
    ],
)
@pytest.mark.parametrize("profile", list(Profile))
def test_word_before_a_protected_span_stays_separated(protected: str, profile: Profile):
    text = f"Call the endpoint at  {protected}  and then stop."
    out = run_pipeline(text, profile=profile)

    assert protected in out.optimized_text
    # Exactly one space either side — collapsed, never removed.
    assert f"at {protected} and" in out.optimized_text, (
        f"whitespace around {protected!r} was destroyed: {out.optimized_text!r}"
    )


@pytest.mark.parametrize("profile", list(Profile))
def test_no_word_gluing_anywhere_in_a_mixed_document(profile: Profile):
    """A whole-document guard: no alphanumeric may end up welded to a scheme,
    a template brace, or an at-sign that it was separated from."""
    text = (
        "Please review  the  config  below  and  reply.\n\n"
        "```python\nx  =  1\n```\n\n"
        "Fetch  https://example.com/a  then  greet  {{name}}  via  ${channel}\n"
        "or  email  ops@example.com  directly.\n"
    )
    out = run_pipeline(text, profile=profile).optimized_text

    for glued in ("https", "{{", "${", "@example"):
        assert f"at{glued}" not in out
    assert " https://example.com/a " in out
    assert " {{name}} " in out
    assert " ${channel}" in out
    assert " ops@example.com " in out


def test_trailing_whitespace_still_trimmed_at_real_line_and_document_ends():
    """The fix must not disable the rule — only stop it firing at span edges."""
    out = run_pipeline("line one   \nline two\t\nlast line   ", profile=Profile.SAFE)
    assert "line one\nline two\nlast line" == out.optimized_text


def test_tier2_rules_are_never_applied_by_any_profile():
    text = "Please summarize this. Thank you very much."
    for profile in Profile:
        out = run_pipeline(text, profile=profile)
        applied_ids = {a.rule.id for a in out.applied}
        assert not any(rid.startswith("flag_") for rid in applied_ids)
        assert "Please" in out.optimized_text


def test_tier2_rule_applies_only_on_explicit_opt_in():
    text = (
        "Summarize the report. Please include the key findings. "
        "Thank you very much for your help."
    )
    out = run_pipeline(text, profile=Profile.SAFE, overrides={"flag_politeness": True})
    assert "Please" not in out.optimized_text
    assert "Thank you" not in out.optimized_text
    assert out.tokens_after < out.tokens_before


def test_a_rule_that_would_cost_tokens_is_rolled_back_and_explained():
    """Shorter text is not always fewer tokens.

    Dropping "Please " here forces "summarize" -> "Summarize", which tokenizes
    worse. The rule must be refused rather than silently making things costlier.
    """
    text = "Please summarize this document carefully."
    out = run_pipeline(text, profile=Profile.SAFE, overrides={"flag_politeness": True})

    assert out.optimized_text == text
    assert out.tokens_after <= out.tokens_before
    assert any("would ADD" in w for w in out.warnings)


def test_suggestions_carry_a_risk_note_and_map_to_original_offsets():
    text = "Please  do the thing. Thank you."
    out = run_pipeline(text, profile=Profile.BALANCED)
    politeness = [s for s in out.suggested if s.rule.id == "flag_politeness"]
    assert politeness, "politeness should be suggested, not applied"
    hit = politeness[0]
    assert hit.rule.semantic_risk_note
    for start, end in hit.spans:
        assert 0 <= start < end <= len(text)


def test_base64_is_flagged_as_advice_not_compressed():
    blob = "A" * 400
    out = run_pipeline(f"Image: {blob}", profile=Profile.BALANCED)
    advisories = [s for s in out.suggested if s.rule.id == "flag_base64"]
    assert advisories
    assert "file" in (advisories[0].advice or "").lower()
    assert blob in out.optimized_text


def test_large_prompt_gets_caching_advice():
    out = run_pipeline("word " * 2000, profile=Profile.BALANCED)
    advice = [s for s in out.suggested if s.rule.id == "advise_prompt_caching"]
    assert advice
    assert "cach" in (advice[0].advice or "").lower()


def test_xml_prompt_delimiters_are_preserved_even_when_aggressive():
    text = "<instructions>\nDo the  thing.\n</instructions>"
    out = run_pipeline(text, profile=Profile.AGGRESSIVE)
    assert "<instructions>" in out.optimized_text
    assert "</instructions>" in out.optimized_text


def test_measure_model_falls_back_to_local_with_a_warning():
    out = run_pipeline("some  text  here", measure_with="claude-opus-5")
    assert out.measure_model == "gpt-4o"
    assert any("local tokenizer" in w for w in out.warnings)


# -- edit machinery ---------------------------------------------------------


def test_edits_apply_in_reverse_order_without_corrupting_offsets():
    text = "aaa bbb ccc"
    edits = [Edit(0, 3, "X"), Edit(4, 7, "Y"), Edit(8, 11, "Z")]
    assert apply_edits(text, edits) == "X Y Z"


def test_overlapping_edits_are_dropped_not_merged():
    edits = [Edit(0, 5, "A"), Edit(3, 8, "B"), Edit(9, 10, "C")]
    kept = resolve_overlaps(edits)
    assert [(e.start, e.end) for e in kept] == [(0, 5), (9, 10)]


def test_every_rule_has_a_unique_id_and_a_risk_note_when_risky():
    ids = [r.id for r in ALL_RULES]
    assert len(ids) == len(set(ids))
    for rule in ALL_RULES:
        if rule.risk.value != "safe":
            assert rule.semantic_risk_note, f"{rule.id} is risky but has no note"
