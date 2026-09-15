from __future__ import annotations

from enricher import _parse_llm_json_text, _remove_trailing_json_commas


def test_parse_repairs_trailing_commas_from_small_model_output() -> None:
    raw = '''
"job_summary": "Builds analytical models.",
"role_domain": "Data & Analytics",
"skills": [
  {"name": "Python (Programming Language)", "required_level": 3},
]
}
'''

    parsed = _parse_llm_json_text(raw, finish_reason="stop")

    assert parsed == {
        "job_summary": "Builds analytical models.",
        "role_domain": "Data & Analytics",
        "skills": [{"name": "Python (Programming Language)", "required_level": 3}],
    }


def test_trailing_comma_repair_does_not_change_string_content() -> None:
    raw = '{"summary":"Keep the literal ,} and ,] text","items":[1,],}'

    repaired = _remove_trailing_json_commas(raw)

    assert repaired == '{"summary":"Keep the literal ,} and ,] text","items":[1]}'
