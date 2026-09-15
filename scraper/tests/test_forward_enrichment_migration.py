from __future__ import annotations

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "create_forward_enrichment_queue.sql"
)
BOOTSTRAP = (
    Path(__file__).resolve().parents[1]
    / "sql"
    / "enable_forward_enrichment_queue.sql"
)


def test_migration_is_forward_only_and_has_no_hash_backfill() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")

    assert "OLD.source_content_hash IS NULL OR OLD.enrichment_status IS NULL" in sql
    assert "UPDATE public.jobs SET source_content_hash" not in sql
    assert "INSERT INTO public.jobs" not in sql
    assert "pgmq.create('job_enrichment')" in bootstrap
    assert "ALTER TABLE public.jobs" not in bootstrap
    assert "pgmq.create('job_enrichment')" not in sql


def test_migration_uses_invoker_functions_and_service_role_only_rpcs() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "SECURITY DEFINER" not in sql
    assert sql.count("SECURITY INVOKER") >= 7
    assert "GRANT EXECUTE ON FUNCTION public.apply_job_enrichment" in sql
    assert "REVOKE ALL ON FUNCTION public.apply_job_enrichment" in sql
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "ON TABLE pgmq.q_job_enrichment, pgmq.a_job_enrichment" in sql
    assert "ON SEQUENCE pgmq.q_job_enrichment_msg_id_seq" in sql
    assert "public.claim_job_enrichment" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "public.request_job_enrichment_priority" in sql
    assert "public.read_priority_job_enrichment" in sql
