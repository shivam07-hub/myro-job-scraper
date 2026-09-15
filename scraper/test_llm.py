"""Isolate inference call — run directly: python3 test_llm.py"""
import json
from openai import OpenAI
from config import INFERENCE_BASE_URL, INFERENCE_API_KEY, INFERENCE_MODEL, INFERENCE_PROVIDER
from enricher import _ENRICH_PROMPT

client = OpenAI(base_url=INFERENCE_BASE_URL, api_key=INFERENCE_API_KEY)

SAMPLE_JD = """
We are hiring a Senior Data Engineer to join our Data Platform team in Bengaluru.

Requirements:
- 5-8 years of experience in data engineering
- Strong proficiency in Python and SQL
- Experience with Apache Spark and Kafka
- Familiarity with AWS (S3, Redshift, Glue)
- Bachelor's degree in Computer Science or related field

Nice to have:
- Experience with dbt or Airflow
- Knowledge of streaming architectures

This is a full-time hybrid role (3 days onsite in Bengaluru).
"""

prompt = _ENRICH_PROMPT.format(
    title="Senior Data Engineer",
    jd=SAMPLE_JD,
    explicit_skill_evidence=json.dumps([
        {"name": "Python (Programming Language)", "required_level": 4, "zone": "mandatory", "evidence": "Strong proficiency in Python and SQL"},
        {"name": "SQL (Programming Language)", "required_level": 4, "zone": "mandatory", "evidence": "Strong proficiency in Python and SQL"},
        {"name": "Apache Spark", "required_level": 2, "zone": "mandatory", "evidence": "Experience with Apache Spark and Kafka"},
        {"name": "Apache Kafka", "required_level": 2, "zone": "mandatory", "evidence": "Experience with Apache Spark and Kafka"},
    ]),
    skills_list="Python (Programming Language), SQL (Programming Language), Apache Spark, Apache Kafka, Amazon Web Services, Data Engineering",
)

print(f"Provider: {INFERENCE_PROVIDER}")
print(f"Model:    {INFERENCE_MODEL}")
print(f"Base URL: {INFERENCE_BASE_URL}")
print(f"Prompt tokens (est): ~{len(prompt)//4}")
print("\nCalling inference endpoint...")

try:
    resp = client.chat.completions.create(
        model=INFERENCE_MODEL,
        messages=[
            {"role": "system", "content": "You are a precise job data extractor. Start your response with { immediately. No preamble, no markdown."},
            {"role": "user",   "content": prompt},
            {"role": "assistant", "content": "{"},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    raw = resp.choices[0].message.content
    print(f"\nRAW RESPONSE:\n{raw}")
    print(f"\nFinish reason: {resp.choices[0].finish_reason}")
    print(f"Tokens — prompt: {resp.usage.prompt_tokens}  completion: {resp.usage.completion_tokens}")
except Exception as e:
    print(f"\nERROR: {type(e).__name__}: {e}")
