-- Repair Workday public apply URLs written without their tenant career-site slug.
--
-- Source of truth: the active Workday rows in KNOWN_PORTALS.md. A read-only
-- production audit on 2026-08-14 found that these 41 hosts cover every affected
-- row, with no conflicts against already-addressable URLs on the same hosts.
--
-- Safety:
--   - only an exact allowlisted host can match;
--   - only paths whose first non-locale segment is /job/ can match;
--   - job identity and verifier/liveness fields are untouched;
--   - the original apply_url is repeated in the UPDATE predicate, so a
--     concurrent correction is not overwritten;
--   - rerunning is idempotent because repaired paths no longer match /job/.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

WITH site_map(host, site) AS (
  VALUES
    ('3m.wd1.myworkdayjobs.com', 'Search'),
    ('abinbev.wd1.myworkdayjobs.com', 'IND'),
    ('accenture.wd103.myworkdayjobs.com', 'AccentureCareers'),
    ('ag.wd3.myworkdayjobs.com', 'Airbus'),
    ('autodesk.wd1.myworkdayjobs.com', 'Ext'),
    ('automationanywhere.wd5.myworkdayjobs.com', 'AutomationAnywhereJobs'),
    ('barclays.wd3.myworkdayjobs.com', 'External_Career_Site_Barclays'),
    ('bb.wd3.myworkdayjobs.com', 'BlackBerry'),
    ('browserstack.wd3.myworkdayjobs.com', 'External'),
    ('carrier.wd5.myworkdayjobs.com', 'jobs'),
    ('cc.wd3.myworkdayjobs.com', 'ChanelCareers'),
    ('cohesity.wd5.myworkdayjobs.com', 'Cohesity_Careers'),
    ('coke.wd1.myworkdayjobs.com', 'coca-cola-careers'),
    ('crowdstrike.wd5.myworkdayjobs.com', 'crowdstrikecareers'),
    ('db.wd3.myworkdayjobs.com', 'DBWebsite'),
    ('dbs.wd3.myworkdayjobs.com', 'DBS_Careers'),
    ('dell.wd1.myworkdayjobs.com', 'External'),
    ('dxctechnology.wd1.myworkdayjobs.com', 'DXCJobs'),
    ('fmr.wd1.myworkdayjobs.com', 'FidelityCareers'),
    ('genpact.wd108.myworkdayjobs.com', 'External_Careers'),
    ('heinz.wd1.myworkdayjobs.com', 'KraftHeinz_Careers'),
    ('intel.wd1.myworkdayjobs.com', 'External'),
    ('kla.wd1.myworkdayjobs.com', 'Search'),
    ('maersk.wd3.myworkdayjobs.com', 'Maersk_Careers'),
    ('mdlz.wd3.myworkdayjobs.com', 'External'),
    ('nike.wd1.myworkdayjobs.com', 'nke'),
    ('novartis.wd3.myworkdayjobs.com', 'Novartis_Careers'),
    ('nxp.wd3.myworkdayjobs.com', 'careers'),
    ('philips.wd3.myworkdayjobs.com', 'jobs-and-careers'),
    ('salesforce.wd12.myworkdayjobs.com', 'External_Career_Site'),
    ('sanofi.wd3.myworkdayjobs.com', 'SanofiCareers'),
    ('sec.wd3.myworkdayjobs.com', 'Samsung_Careers'),
    ('shell.wd3.myworkdayjobs.com', 'ShellCareers'),
    ('sprinklr.wd1.myworkdayjobs.com', 'careers'),
    ('statestreet.wd1.myworkdayjobs.com', 'Global'),
    ('target.wd5.myworkdayjobs.com', 'TargetCareers'),
    ('thomsonreuters.wd5.myworkdayjobs.com', 'External_Career_Site'),
    ('thoughtspot.wd5.myworkdayjobs.com', 'careers'),
    ('vanguard.wd5.myworkdayjobs.com', 'vanguard_external'),
    ('wf.wd1.myworkdayjobs.com', 'WellsFargoJobs'),
    ('workday.wd5.myworkdayjobs.com', 'Workday')
), candidates AS MATERIALIZED (
  SELECT
    j.job_id,
    j.apply_url AS original_url,
    regexp_replace(
      j.apply_url,
      '^((?:https?://[^/]+/)(?:[a-z]{2}(?:-[a-z]{2})?/)?)(job/)',
      '\1' || sm.site || '/\2',
      'i'
    ) AS repaired_url
  FROM public.jobs AS j
  JOIN site_map AS sm
    ON lower(split_part(split_part(j.apply_url, '://', 2), '/', 1)) = sm.host
  WHERE j.apply_url ~* '^https?://[^/]+/(?:[a-z]{2}(?:-[a-z]{2})?/)?job/'
), updated AS (
  UPDATE public.jobs AS j
  SET apply_url = c.repaired_url
  FROM candidates AS c
  WHERE j.job_id = c.job_id
    AND j.apply_url = c.original_url
    AND c.repaired_url IS DISTINCT FROM c.original_url
  RETURNING j.job_id
)
SELECT count(*) AS repaired_jobs
FROM updated;

COMMIT;
