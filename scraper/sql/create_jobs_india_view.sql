-- Downstream India filter view for global-only ingestion.
-- Keeps ingestion scope global while exposing an India slice for consumers.

create or replace view public.jobs_india as
select *
from public.jobs
where
  coalesce(location, '') ilike '%india%'
  or coalesce(location, '') ilike '%bengaluru%'
  or coalesce(location, '') ilike '%bangalore%'
  or coalesce(location, '') ilike '%hyderabad%'
  or coalesce(location, '') ilike '%mumbai%'
  or coalesce(location, '') ilike '%pune%'
  or coalesce(location, '') ilike '%chennai%'
  or coalesce(location, '') ilike '%delhi%'
  or coalesce(location, '') ilike '%gurgaon%'
  or coalesce(location, '') ilike '%gurugram%'
  or coalesce(location, '') ilike '%noida%'
  or coalesce(location, '') ilike '%kolkata%'
  or coalesce(location, '') ilike '%ahmedabad%';
