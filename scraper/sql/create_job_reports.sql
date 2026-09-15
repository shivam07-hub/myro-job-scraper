-- job_reports table + deactivation trigger
-- Run AFTER add_phase3_columns.sql

CREATE TABLE IF NOT EXISTS public.job_reports (
  id          BIGSERIAL PRIMARY KEY,
  job_id      TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  reported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (job_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_job_reports_job_id    ON job_reports(job_id);
CREATE INDEX IF NOT EXISTS idx_job_reports_user_id   ON job_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_job_reports_user_date ON job_reports(user_id, reported_at DESC);

-- Trigger: increment report_count; deactivate at 5
CREATE OR REPLACE FUNCTION fn_job_report_deactivation()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE jobs
  SET
    report_count = report_count + 1,
    is_active    = CASE WHEN report_count + 1 >= 5 THEN false ELSE is_active END
  WHERE job_id = NEW.job_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_job_report_deactivation ON job_reports;
CREATE TRIGGER trg_job_report_deactivation
AFTER INSERT ON job_reports
FOR EACH ROW EXECUTE FUNCTION fn_job_report_deactivation();

ALTER TABLE job_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users can insert own reports"
  ON job_reports FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "reports readable by authenticated"
  ON job_reports FOR SELECT
  USING (auth.role() = 'authenticated');
