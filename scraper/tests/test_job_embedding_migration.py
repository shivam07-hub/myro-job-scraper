from __future__ import annotations

from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "create_job_embeddings.sql"


def test_vectors_are_private_and_service_role_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "private.job_embeddings" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "public.halfvec(768)" in sql
    assert "USING hnsw" in sql
    assert "SECURITY DEFINER" not in sql
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "TO service_role" in sql
    assert "ALTER TABLE public.jobs" not in sql


def test_backfill_is_limited_to_recent_active_postings() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "recent_posted_backfill_14d" in sql
    assert "j.is_active IS TRUE" in sql
    assert "j.posted_on BETWEEN" in sql
    assert "AT TIME ZONE 'Asia/Kolkata'" in sql
    assert "j.date_posted" in sql
    assert "j.first_seen" not in sql
    assert "UPDATE public.jobs SET" not in sql


def test_claim_order_matches_the_partial_work_index() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ON private.job_embeddings (queued_at, job_id)" in sql
    assert "ORDER BY je.queued_at, je.job_id" in sql


def test_semantic_rpc_has_metadata_filters_but_no_score_sieve() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    function = sql.split("CREATE OR REPLACE FUNCTION public.match_jobs_semantic", 1)[1]
    function = function.split("CREATE OR REPLACE FUNCTION public.job_embedding_metrics", 1)[0]
    assert "j.is_active IS TRUE" in function
    assert "listing_confidence" in function
    assert "p_target_countries" in function
    assert "p_excluded_job_ids" in function
    assert "match_threshold" not in function
    assert "ORDER BY je.embedding OPERATOR(public.<=>)" in function
