NORMALIZE_SYSTEM_PROMPT = """\
You normalize interview-question candidates into original multiple-choice questions.
Return one JSON object only. Never quote or closely copy the source wording.
Reject ambiguous, opinion-based, multi-answer, context-dependent, or malformed candidates."""


NORMALIZE_USER_PROMPT = """\
Skill: {skill_key}
Skill description: {skill_description}
Requested level: {target_level}

Transient source candidate:
{candidate_text}

Rewrite the underlying concept as one original, self-contained MCQ.
Use exactly four distinct options and exactly one correct answer.
The explanation must be one sentence stating the decisive reason.

Difficulty:
1 = direct recall
2 = concept recognition
3 = applied scenario
4 = multi-factor analysis
5 = architecture, strategy, or competing constraints

Return exactly:
{{
  "question_text": "",
  "options": ["", "", "", ""],
  "correct_index": 0,
  "explanation": "",
  "level": 1,
  "rejected": false,
  "rejection_reason": ""
}}"""


VERIFY_SYSTEM_PROMPT = """\
You independently verify multiple-choice questions.
Choose the single best answer without relying on any previous answer key.
Mark the question ambiguous when more than one option is defensible or context is missing.
Return one JSON object only."""


VERIFY_USER_PROMPT = """\
Skill: {skill_key}
Skill description: {skill_description}

Question:
{question_text}

Options:
{options_text}

Return exactly:
{{
  "correct_index": 0,
  "ambiguous": false,
  "rationale": "",
  "suggested_level": 1
}}"""

