from question_bank.supabase_writer import QuestionBankSupabase, plan_upserts


DB_ROW = {
    "skill_id": 2772,
    "skill_key": "Machine Learning",
    "level": 2,
    "question_text": "Which metric balances precision and recall?",
    "options": ["Accuracy", "F1 score", "R-squared", "MAE"],
    "correct_index": 1,
    "explanation": "F1 score is the harmonic mean of precision and recall.",
    "source_url": "https://example.org/source",
    "dedupe_hash": "hash-1",
    "status": "active",
    "review_reasons": [],
    "raw_hash": "raw-1",
}


def test_plan_never_downgrades_existing_active_row() -> None:
    incoming = [{**DB_ROW, "status": "review"}]
    existing = [{**DB_ROW, "status": "active"}]

    assert plan_upserts(incoming, existing) == []


def test_plan_promotes_review_row_after_verification() -> None:
    incoming = [{**DB_ROW, "status": "active"}]
    existing = [{**DB_ROW, "status": "review"}]

    assert plan_upserts(incoming, existing) == [incoming[0]]


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def get(self, url, **kwargs):
        self.gets.append({"url": url, **kwargs})
        if url.endswith("/rest/v1/"):
            return FakeResponse({
                "definitions": {
                    "skill_questions": {
                        "properties": {
                            "skill_id": {},
                            "skill_key": {},
                            "level": {},
                            "question_text": {},
                            "options": {},
                            "correct_index": {},
                            "explanation": {},
                            "source_url": {},
                            "dedupe_hash": {},
                            "status": {},
                        }
                    }
                }
            })
        return FakeResponse([])

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakeResponse(status_code=201)


def test_preflight_accepts_expected_live_columns() -> None:
    writer = QuestionBankSupabase("https://project.supabase.co", "service-key", session=FakeSession())

    writer.preflight()


def test_dry_run_makes_no_writes() -> None:
    session = FakeSession()
    writer = QuestionBankSupabase("https://project.supabase.co", "service-key", session=session)

    result = writer.publish([DB_ROW], existing_rows=[], dry_run=True)

    assert result.planned == 1
    assert result.written == 0
    assert session.posts == []


def test_publish_batches_and_strips_local_diagnostics() -> None:
    session = FakeSession()
    writer = QuestionBankSupabase("https://project.supabase.co", "service-key", session=session)
    rows = [
        {
            **DB_ROW,
            "dedupe_hash": f"hash-{index}",
            "question_text": f"Question {index}?",
        }
        for index in range(205)
    ]

    result = writer.publish(rows, existing_rows=[], dry_run=False)

    assert result.written == 205
    assert len(session.posts) == 3
    assert "review_reasons" not in session.posts[0]["json"][0]
    assert "raw_hash" not in session.posts[0]["json"][0]

