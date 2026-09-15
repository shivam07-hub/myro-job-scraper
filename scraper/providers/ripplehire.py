from __future__ import annotations

"""RippleHire ATS provider.

Pattern:
  1) GET https://{host}/candidate/?token={token}&source=CAREERSITE  → acquire JSESSIONID
  2) POST https://{host}/candidate/candidatejobsearch
     form-encoded: careerSiteUrlParams (JSON), lang=en
     careerSiteUrlParams fields: page, search, token, source, pagesize, location
  3) Filter India client-side via is_india()
"""

import json
import logging
import re
from urllib.parse import urlencode

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")
_PAGE_SIZE = 50
_NON_INDIA_LOCATION_RE = re.compile(
    r"\b(united states|usa|canada|singapore|malaysia|australia|germany|france|uk|united kingdom)\b",
    re.IGNORECASE,
)


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}


class RippleHireProvider:
    key = "ripplehire"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            jobs = _scrape_ripplehire(portal, max_jobs=max_jobs)
        except requests.RequestException as e:
            _log.error(f"    [ERROR] RippleHire {portal.get('company')}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_ripplehire(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    host = portal.get("ripplehire_host", "").strip()
    token = portal.get("ripplehire_token", "").strip()
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)

    if not host or not token:
        _log.error(f"    [RippleHire] {company}: missing ripplehire_host or ripplehire_token")
        return None

    base = f"https://{host}"
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Origin": base, "Referer": f"{base}/"})

    # Acquire session cookie
    try:
        sess.get(
            f"{base}/candidate/",
            params={"token": token, "source": "CAREERSITE"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except Exception as e:
        _log.warning(f"    [RippleHire] {company}: session acquire failed ({e}); proceeding anyway")

    search_url = f"{base}/candidate/candidatejobsearch"
    jobs: list[dict] = []
    page = 0

    while True:
        params_obj = {
            "page": page,
            "search": "*:*",
            "token": token,
            "source": "CAREERSITE",
            "pagesize": _PAGE_SIZE,
            "location": "",
        }
        try:
            r = sess.post(
                search_url,
                data={"careerSiteUrlParams": json.dumps(params_obj), "lang": "en"},
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] RippleHire {company} page={page}: {e}")
            return jobs or None

        docs = _extract_listing_docs(payload)
        if not docs:
            break

        for doc in docs:
            detail_payload = _fetch_detail_payload(sess, base, token, doc)
            if detail_payload:
                doc = _merge_detail_payload(doc, detail_payload)

            job = _doc_to_job(doc, portal, base, search_url)
            if not job:
                continue
            jobs.append(job)

            if max_jobs and len(jobs) >= max_jobs:
                _log.info(f"    {company}: {len(jobs)} India jobs via RippleHire [cap]")
                return jobs

        if len(docs) < _PAGE_SIZE:
            break
        page += 1

    _log.info(f"    {company}: {len(jobs)} India jobs via RippleHire")
    return jobs


def _extract_listing_docs(payload: dict) -> list[dict]:
    """Normalize RippleHire listing shapes seen across tenants."""
    response_obj = payload.get("response") or payload
    docs = (
        response_obj.get("docs")
        or response_obj.get("jobs")
        or response_obj.get("jobVoList")
        or response_obj.get("jobVOList")
        or payload.get("jobVoList")
        or []
    )
    return docs if isinstance(docs, list) else []


def _job_seq(doc: dict) -> str:
    return str(
        doc.get("jobSeq")
        or doc.get("jobseq")
        or doc.get("jobid")
        or doc.get("id")
        or doc.get("jobId")
        or doc.get("job_id")
        or ""
    ).strip()


def _location_text(value) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("name") or item.get("location") or item.get("city") or ""))
            else:
                parts.append(str(item or ""))
        return ", ".join(p.strip() for p in parts if p and p.strip())
    if isinstance(value, dict):
        return str(value.get("name") or value.get("location") or value.get("city") or "").strip()
    return str(value or "").strip()


def _is_allowed_location(loc: str, india_only: bool) -> bool:
    if not india_only:
        return True
    if not loc:
        return True
    if is_india(loc):
        return True
    # Some India-only RippleHire tenants return only city/site names such as
    # Kalaburagi or West Bokaro. Reject explicit foreign countries, otherwise
    # trust the company-specific India portal.
    return not _NON_INDIA_LOCATION_RE.search(loc)


def _fetch_detail_payload(sess: requests.Session, base: str, token: str, doc: dict) -> dict:
    seq = _job_seq(doc)
    if not seq:
        return {}
    detail_url = f"{base}/candidate/candidatejobdetail"
    params = {
        "jobSeq": seq,
        "token": token,
        "source": "CAREERSITE",
        "lang": "en",
    }
    try:
        r = sess.get(detail_url, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}


def _merge_detail_payload(doc: dict, payload: dict) -> dict:
    detail = payload.get("jobVO") or payload.get("jobVo") or payload.get("job") or payload
    if not isinstance(detail, dict):
        return doc
    merged = dict(doc)
    merged.update({k: v for k, v in detail.items() if v not in (None, "")})
    return merged


def _doc_to_job(doc: dict, portal: Portal, base: str, search_url: str) -> dict | None:
    company = portal.get("company", "")
    title = (
        doc.get("jobTitle")
        or doc.get("title")
        or doc.get("job_title")
        or doc.get("designation")
        or ""
    )
    title = str(title).strip()
    if not title:
        return None

    loc = _location_text(
        doc.get("locations")
        or doc.get("location")
        or doc.get("city")
        or doc.get("jobLocation")
        or doc.get("jobCity")
        or ""
    )
    if not _is_allowed_location(loc, portal.get("india_only", True)):
        return None

    jid = _job_seq(doc)
    detail_params = {"jobSeq": jid, "source": "CAREERSITE"} if jid else {}
    if portal.get("ripplehire_token"):
        detail_params["token"] = portal["ripplehire_token"]
    apply_url = f"{base}/candidate/candidatejobdetail"
    if detail_params:
        apply_url = f"{apply_url}?{urlencode(detail_params)}"

    raw_jd = strip_html(
        doc.get("jobDesc")
        or doc.get("shortDescription")
        or doc.get("longDescription")
        or doc.get("jobDescription")
        or doc.get("responsibility")
        or ""
    )

    return {
        "job_id":          jid or f"{company}_{title[:40]}",
        "title":           title,
        "job_url":         apply_url,
        "source_api_url":  search_url,
        "business_unit":   doc.get("departmentName") or doc.get("department") or doc.get("division"),
        "raw_jd_text":     raw_jd,
        "location_city":   loc or "India",
        "date_posted":     doc.get("modifiedDate") or doc.get("postedDate") or doc.get("createdDate"),
        "source_platform": "RippleHire",
        "industry":        portal.get("industry", ""),
    }
