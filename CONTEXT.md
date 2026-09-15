# Job feed publication

Source snapshots of company career listings, published into the live job feed.

## Language

**Source snapshot**:
The scrape-owned fields of a job from one complete run date — title, JD, location, apply URL, seniority, career band, and a first-fill extractive card summary.
_Avoid_: dump, scrape blob, raw JSON

**Source snapshot writer**:
The module that writes a **Source snapshot** and then closes the feed. Callers do not know PostgREST column-union. Physical delete is True_Yodha after a one-hour quarantine.
_Avoid_: importer internals, upsert helper, lifecycle hook

**Model-owned field**:
A column the open-weight enrichment pass upgrades (`job_summary` once filled, `role_domain`, enrichment hashes/status). A **Source snapshot** must not NULL or overwrite a non-empty one.
_Avoid_: enrichment payload, LLM columns

**Feed close**:
After a complete source write: presence evidence (seen / missing), and on a full-scope run the 30-day age backstop. Closed listings wait one hour; True_Yodha archives them to disk then deletes.
_Avoid_: delist, deactivate, retire (age-delist closes the card; unload is a later True_Yodha step)

## Relationships

- A **Source snapshot writer** publishes one **Source snapshot** per company in the run, then performs **Feed close**
- A **Model-owned field** is never written by a **Source snapshot** except first-fill empty `job_summary`
- `--company` canaries skip the age step of **Feed close**; they never delete rows

## Example dialogue

> **Dev:** "Can the importer omit `job_summary` on rows that already have an LLM card so we don't overwrite them?"
> **Domain expert:** "Omit is the **Source snapshot** policy. The **Source snapshot writer** must make omit safe: PostgREST treats a missing key in a mixed batch as NULL, which wipes a **Model-owned field**."

## Flagged ambiguities

- "retire" in True_Yodha verifier logs means archive-then-delete after the one-hour clock, not the 30-day age backstop and not `--deactivate-missing`
