"""Guards the Workday requisition-id capture (docs/reports/2026-06-21-*).

Regression: the CXS list endpoint returns no `jobReqId`, so the provider must
derive the requisition id from `bulletFields[0]` / the `_R…` path tail instead of
falling back to the dedup hash for every Workday posting.
"""

from utils import workday_req_id


def test_req_id_from_bullet_fields():
    posting = {"bulletFields": ["R01165624", "Supply Chain"]}
    assert workday_req_id(posting, "/job/IN-Delhi/Foo_R99999999") == "R01165624"


def test_req_id_from_path_tail_when_no_bullet_fields():
    posting = {"bulletFields": []}
    ext = "/job/IN-BANGALORE/Specialist--COGS--Supply-Chain-_R01165581"
    assert workday_req_id(posting, ext) == "R01165581"


def test_req_id_none_when_neither_present():
    assert workday_req_id({}, "/job/IN-Bangalore/Some-Role") is None


def test_blank_bullet_field_falls_through_to_path():
    posting = {"bulletFields": ["  "]}
    assert workday_req_id(posting, "/job/x/Role_JR123456") == "JR123456"
