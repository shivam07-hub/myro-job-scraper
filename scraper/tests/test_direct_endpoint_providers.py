from __future__ import annotations

import json
import re

import providers.generic_json as generic_json
import providers.talent500 as talent500
import providers.trakstar as trakstar
from providers.apple_jobs import parse_apple_search_result
from providers.cognizant_xml import parse_cognizant_xml
from providers.cornerstone import (
    merge_cornerstone_detail,
    parse_cornerstone_search_payload,
)
from providers.deshaw_india import parse_deshaw_next_data
from providers.google_careers import parse_google_careers_html
from providers.hilabs_careers import parse_hilabs_html
from providers.icims_html import parse_icims_html_listing
from providers.intouchcx import (
    parse_dayforce_next_data,
    parse_intouchcx_feed,
    parse_legacy_intouchcx_detail,
)
from providers.blackbrix_jobs import (
    parse_blackbrix_detail,
    parse_blackbrix_listing_items,
)
from providers.ashby import parse_ashby_job_board
from providers.dejobs_rss import parse_dejobs_rss
from providers.microsoft_careers import (
    parse_microsoft_detail_payload,
    parse_microsoft_search_payload,
)
from providers.publicis_sapient import parse_publicis_search_payload
from providers.rippling import parse_rippling_detail_page, parse_rippling_listing_page
from providers.tata_elxsi import extract_tata_elxsi_detail, extract_tata_elxsi_listing_items
from providers.talentbrew import _extract_listing_items, _page_url
from providers.vector_consulting import parse_vector_next_data


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


class _FakeJSONResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_radancy_listing_links_parse() -> None:
    html = """
    <li class="sr-job-item">
      <h3 class="sr-job-item__title">
        <a class="sr-job-item__link" href="/job/mumbai/head-of-equites-india-onshore-team/287/94768478096" data-job-id="94768478096">
          Head Of Equites India Onshore Team
        </a>
      </h3>
      <span class="sr-job-item__facet sr-job-location">Mumbai, Maharashtra, India</span>
    </li>
    <li>
      <a class="search-results-link" href="/job/mumbai/head-distribution-and-retail/7684/94758247168" data-job-id="94758247168">
        <div><h2>Head Distribution and Retail</h2><span class="job-location">Mumbai, Maharashtra, India</span></div>
      </a>
    </li>
    """
    items = _extract_listing_items(html)
    check("radancy item count", len(items) == 2)
    check("citi title parsed", items[0]["title"] == "Head Of Equites India Onshore Team")
    check("astrazeneca title parsed", items[1]["title"] == "Head Distribution and Retail")
    check("location parsed", items[1]["listing_loc"] == "Mumbai, Maharashtra, India")


def test_radancy_job_card_links_parse() -> None:
    html = """
    <ul id="search-results-jobs" data-results-count="38">
      <li class="job-card fs-start">
        <a class="job-card__title fs-11" href="/job/bengaluru/finance-operations-analyst/33099/94956016624" data-job-id="94956016624">
          Finance Operations Analyst
        </a>
        <span class="location">Bengaluru, India</span>
        <span class="category">Finance &amp; Accounting</span>
      </li>
    </ul>
    """
    items = _extract_listing_items(html)
    check("job-card item count", len(items) == 1)
    check("job-card id parsed", items[0]["job_id"] == "94956016624")
    check("job-card title parsed", items[0]["title"] == "Finance Operations Analyst")
    check("job-card location parsed", items[0]["listing_loc"] == "Bengaluru, India")


def test_palo_alto_section29_links_parse() -> None:
    html = """
    <ul class="section29__search-results-ul" data-total-job-results="104">
      <li class="section29__search-results-li">
        <a class="section29__search-results-link" href="/en/job/bengaluru/principal-devops-engineer/47263/95005127232" data-job-id="95005127232">
          <h2 class="section29__search-results-job-title">Principal DevOps Engineer</h2>
          <div class="section29__result-info-container">
            <span class="section29__result-location">Bengaluru, Karnataka, India</span>
          </div>
        </a>
      </li>
    </ul>
    """
    items = _extract_listing_items(html)
    check("palo alto section29 item count", len(items) == 1)
    check("palo alto section29 id", items[0]["job_id"] == "95005127232")
    check("palo alto section29 title", items[0]["title"] == "Principal DevOps Engineer")
    check("palo alto section29 location", items[0]["listing_loc"] == "Bengaluru, Karnataka, India")


def test_cargill_bare_talentbrew_links_parse() -> None:
    html = """
    <a href="/en/job/bengaluru/senior-data-engineer/23251/95123456784" data-job-id="95123456784">
      <h3>Senior Data Engineer</h3>
      <span class="job-location">Bengaluru, India</span>
    </a>
    """
    items = _extract_listing_items(html)
    check("cargill bare item count", len(items) == 1)
    check("cargill bare id", items[0]["job_id"] == "95123456784")
    check("cargill bare title", items[0]["title"] == "Senior Data Engineer")
    check("cargill bare location", items[0]["listing_loc"] == "Bengaluru, India")


def test_icims_html_listing_parser_maps_job_cards() -> None:
    html = """
    <ul class="container-fluid iCIMS_JobsTable">
      <li class="iCIMS_JobCardItem">
        <div class="row">
          <div class="col-xs-6 header left">
            <span class="sr-only field-label">Job Locations</span>
            <span>IN-Hyderabad</span>
          </div>
          <div class="col-xs-12 title">
            <a href="https://incareers-jaggaer.icims.com/jobs/4082/data-scientist/job?in_iframe=1" class="iCIMS_Anchor" title="4082 - Data Scientist">
              <span class="sr-only field-label">Job Title</span>
              <h3>Data Scientist</h3>
            </a>
          </div>
          <div class="col-xs-12 additionalFields">
            <dl class="iCIMS_JobHeaderGroup">
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Job ID</dt>
                <dd class="iCIMS_JobHeaderData"><span>2026-4082</span></dd>
              </div>
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Category</dt>
                <dd class="iCIMS_JobHeaderData"><span>Development</span></dd>
              </div>
              <div class="iCIMS_JobHeaderTag">
                <dt class="iCIMS_JobHeaderField">Overview</dt>
                <dd class="iCIMS_JobHeaderData"><span>&lt;p&gt;Build AI procurement products.&lt;/p&gt;</span></dd>
              </div>
            </dl>
          </div>
        </div>
      </li>
    </ul>
    """
    jobs = parse_icims_html_listing(
        html,
        {
            "company": "JAGGAER",
            "endpoint": "https://incareers-jaggaer.icims.com/jobs/search?ss=1&hashed=-435832948&mobile=false&country=IN",
            "industry": "Technology",
            "india_only": True,
        },
    )
    check("icims html filters india", len(jobs) == 1)
    check("icims html id", jobs[0]["job_id"] == "2026-4082")
    check("icims html title", jobs[0]["title"] == "Data Scientist")
    check("icims html jd", "AI procurement products" in jobs[0]["raw_jd_text"])
    check("icims html location", jobs[0]["location_city"] == "IN-Hyderabad")


def test_search_jobs_pagination_uses_p_param() -> None:
    url = _page_url("https://jobs.citi.com/search-jobs/India", 2)
    check("search-jobs page param", url == "https://jobs.citi.com/search-jobs/India?p=2")


def test_publicis_search_payload_maps_india_docs() -> None:
    payload = {
        "response": {
            "numFound": 2,
            "docs": [
                {
                    "id": "2025-128894",
                    "name": "Senior Manager People Shared Services",
                    "city": "Gurgaon",
                    "countryName": "India",
                    "jobId": "2025-128894",
                    "jobUrl": "https://sapient-publicisgroupe.icims.com/jobs/128894/job/login",
                    "jobDetailUrl": "/job-details/2025-128894-senior-manager-people-shared-services-gurgaon",
                    "description": "Lead people services.",
                    "teams": "People Strategy",
                },
                {
                    "id": "2025-999",
                    "name": "US Role",
                    "city": "New York",
                    "countryName": "United States",
                },
            ],
        }
    }
    jobs = parse_publicis_search_payload(
        payload,
        {
            "endpoint": "https://careers.publicissapient.com/apps/ps-rebrand/careersJobsearch?q=&country=India",
            "industry": "Consulting",
            "india_only": True,
        },
    )
    check("publicis filters india", len(jobs) == 1)
    check("publicis id", jobs[0]["job_id"] == "2025-128894")
    check("publicis title", jobs[0]["title"] == "Senior Manager People Shared Services")
    check("publicis detail url", jobs[0]["job_url"].endswith("/job-details/2025-128894-senior-manager-people-shared-services-gurgaon"))


def test_cognizant_xml_parser_filters_india() -> None:
    xml = """<?xml version="1.0"?>
    <source>
      <job>
        <title><![CDATA[India Engineer]]></title>
        <requisitionid><![CDATA[0001]]></requisitionid>
        <url><![CDATA[https://careers.cognizant.com/india-en/jobs/0001/india-engineer/]]></url>
        <city><![CDATA[BANGALORE]]></city>
        <state><![CDATA[Karnataka]]></state>
        <country><![CDATA[India]]></country>
        <description><![CDATA[<p>Build platforms.</p>]]></description>
        <category><![CDATA[Technology]]></category>
        <date><![CDATA[Fri, 08 May 2026 09:26:46 GMT]]></date>
      </job>
      <job>
        <title><![CDATA[US Engineer]]></title>
        <requisitionid><![CDATA[0002]]></requisitionid>
        <url><![CDATA[https://careers.cognizant.com/us/jobs/0002/us-engineer/]]></url>
        <city><![CDATA[Orlando]]></city>
        <state><![CDATA[Florida]]></state>
        <country><![CDATA[United States]]></country>
        <description><![CDATA[<p>Build platforms.</p>]]></description>
      </job>
    </source>
    """
    jobs = parse_cognizant_xml(xml, {"company": "Cognizant", "industry": "IT Services", "india_only": True})
    check("only india job parsed", len(jobs) == 1)
    check("cognizant title", jobs[0]["title"] == "India Engineer")
    check("cognizant jd stripped", jobs[0]["raw_jd_text"] == "Build platforms.")


def test_apple_search_result_maps_india_job() -> None:
    item = {
        "positionId": "200314033",
        "postingTitle": "IN-Operations Expert",
        "jobSummary": "Retail operations role.",
        "postingDate": "08 May 2026",
        "team": "Apple Retail",
        "locations": [{
            "name": "India",
            "countryName": "India",
            "countryID": "iso-country-IND",
        }],
    }
    job = parse_apple_search_result(item, {"endpoint": "https://jobs.apple.com/api/v1/search", "industry": "Technology"})
    check("apple job parsed", job is not None)
    check("apple title", job["title"] == "IN-Operations Expert")
    check("apple location", "India" in job["location_city"])


def test_tata_elxsi_listing_cards_parse() -> None:
    html = """
    <div id="job_listing">
      <div class="jjbcdeo1 botm1">
        <div class="jjbcdeo11">
          <h5>RFH/06328</h5>
          <h3>RDK-B Developer</h3>
          <p>Bangalore/Chennai | 5 - 10 years | B.E, B.Tech | RDK-B-Developer</p>
        </div>
        <div class="jjbcdeo12">
          <p>07 May 2026</p>
          <a href="https://www.tataelxsi.com/careers/job-openings/rdk-b-developer-2" class="jknmre">Know More</a>
        </div>
      </div>
      <div class="jjbcdeo1 botm1">
        <div class="jjbcdeo11">
          <h5>Functional Safety Engineer</h5>
          <h3>Functional Safety Engineer</h3>
          <p>London / Coventry | 3 - 5 years | Bachelors / Masters | Functional Safety Engineer</p>
        </div>
        <div class="jjbcdeo12">
          <p>04 May 2026</p>
          <a href="/careers/job-openings/functional-safety-engineer" class="jknmre">Know More</a>
        </div>
      </div>
    </div>
    """
    items = extract_tata_elxsi_listing_items(html, "https://www.tataelxsi.com/careers/job-openings")
    check("tata listing count", len(items) == 2)
    check("tata title parsed", items[0]["title"] == "RDK-B Developer")
    check("tata job code parsed", items[0]["job_code"] == "RFH/06328")
    check("tata location parsed", items[0]["location"] == "Bangalore/Chennai")
    check("tata non-india retained for caller filter", items[1]["location"] == "London / Coventry")


def test_tata_elxsi_detail_extracts_jd_and_apply_url() -> None:
    html = """
    <section id="japlicatn">
      <div class="jbpam botm1">
        <h2>RDK-B Developer</h2>
        <div class="aplynw">
          <a href="https://tataelxsi.ramcoes.com/rvw/PortalBroadBeanCalling.aspx?rfhno=15~RFH/06328" class="japlynw">Apply Now</a>
        </div>
      </div>
      <div class="jbpam1">
        <p>Tata Elxsi offers comprehensive services in Media and Communications.</p>
        <p><strong>Job Description:</strong></p>
        <ul>
          <li>5+ years of experience in embedded software development.</li>
          <li>Strong programming skills in C/C++.</li>
        </ul>
      </div>
    </section>
    """
    detail = extract_tata_elxsi_detail(html, "https://www.tataelxsi.com/careers/job-openings/rdk-b-developer-2")
    check("tata detail title", detail["title"] == "RDK-B Developer")
    check("tata detail apply url", detail["apply_url"].startswith("https://tataelxsi.ramcoes.com/"))
    check("tata detail jd", "embedded software development" in detail["raw_jd_text"])


def test_vector_next_data_parser_maps_jobs_and_body_sections() -> None:
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "jobsData": {
            "dataset": [
              {
                "id": 39,
                "job_title": "Project Management Consultant",
                "slug": "project-management-consultant",
                "job_role": "Project Management Consultant",
                "location": "India",
                "employment_type": "Full time employment",
                "years_of_experience": "5-7 years",
                "description": "<p>Vector Consulting Group overview.</p>",
                "body": "[{\\"title\\":\\"Role & Responsibilities:\\",\\"content\\":\\"<ul><li>Lead consulting workstreams.</li></ul>\\"}]"
              },
              {
                "id": 40,
                "job_title": "Indonesia Consultant",
                "slug": "indonesia-consultant",
                "location": "Indonesia",
                "description": "<p>Non-India role.</p>",
                "body": []
              }
            ]
          }
        }
      }
    }
    </script>
    """
    jobs = parse_vector_next_data(
        html,
        {"company": "Vector Consulting Group", "industry": "Consulting", "india_only": True},
        "https://www.vectorconsulting.in/careers/career-listings/",
    )
    check("vector filters india", len(jobs) == 1)
    check("vector title", jobs[0]["title"] == "Project Management Consultant")
    check("vector body jd", "Lead consulting workstreams" in jobs[0]["raw_jd_text"])
    check("vector job url", jobs[0]["job_url"].endswith("/careers/career-listings/project-management-consultant"))


def test_oracle_nested_scraper_paginates_offsets() -> None:
    calls: list[str] = []
    original_get = generic_json.requests.get

    def fake_get(url: str, headers=None, timeout=None):
        calls.append(url)
        limit = int(re.search(r'limit=(\d+)', url).group(1))
        offset = int(re.search(r'offset=(\d+)', url).group(1))
        total = 140
        page = []
        for idx in range(offset, min(offset + limit, total)):
            page.append({
                "Id": 26000000 + idx,
                "Title": f"Oracle Job {idx}",
                "PrimaryLocation": "Bengaluru, KA, India",
                "ExternalDescriptionStr": f"<p>Role {idx} {'x' * 1300}</p>",
            })
        return _FakeJSONResponse({"items": [{"TotalJobsCount": total, "requisitionList": page}]})

    generic_json.requests.get = fake_get
    try:
        portal = {
            "company": "American Express",
            "ats": "oracle",
            "oracle_nested": True,
            "india_only": True,
            "industry": "Financial Services",
            "endpoint": (
                "https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
                "recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.workLocation,"
                "requisitionList.otherWorkLocations,requisitionList.secondaryLocations,"
                "flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder=findReqs;"
                "siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3B"
                "CATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit=25,"
                "locationId=300000000228786,sortBy=POSTING_DATES_DESC"
            ),
        }
        jobs = generic_json.scrape_get(portal, max_jobs=140)
        check("oracle pagination job count", len(jobs) == 140)
        check("oracle pagination second page fetched", len(calls) == 2 and "offset=100" in calls[1])
        check("oracle pagination jd parsed", jobs[0]["raw_jd_text"].startswith("Role 0"))
    finally:
        generic_json.requests.get = original_get


def test_deshaw_next_data_parser_maps_public_regular_jobs() -> None:
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "regularJobs": [
            {
              "data": {
                "id": 6760,
                "displayName": "Core Tech/Principal Manager, Tech (Treasury Tech)",
                "isActive": true,
                "jobUrl": "Core-Tech-Principal-Manager-Tech-Treasury-Tech-6760",
                "jobHeaders": ["INFORMATION TECHNOLOGY"],
                "department": {"name": "Core Tech"},
                "jobMetadata": {
                  "activeOnWebsite": true,
                  "jobLocations": [{"name": "Bengaluru"}]
                },
                "jobDescription": {
                  "websiteDescription": "We are looking for an exceptional Principal Manager.",
                  "peopleWeAreLookingFor": ["Must have proficiency in Python."],
                  "peopleWeAreLookingForHtml": "<ul><li>8 to 12 years of Software Engineering experience.</li></ul>"
                }
              }
            },
            {
              "data": {
                "id": 10,
                "displayName": "US Role",
                "isActive": true,
                "jobUrl": "US-Role-10",
                "jobMetadata": {
                  "activeOnWebsite": true,
                  "jobLocations": [{"name": "New York"}]
                },
                "jobDescription": {"websiteDescription": "US role."}
              }
            }
          ]
        }
      }
    }
    </script>
    """
    jobs = parse_deshaw_next_data(
        html,
        {"company": "DE Shaw", "industry": "BFSI", "india_only": True},
        "https://www.deshawindia.com/careers",
    )
    check("deshaw filters india", len(jobs) == 1)
    check("deshaw title", jobs[0]["title"] == "Core Tech/Principal Manager, Tech (Treasury Tech)")
    check("deshaw jd sections", "Software Engineering experience" in jobs[0]["raw_jd_text"])
    check("deshaw list jd sections", "proficiency in Python" in jobs[0]["raw_jd_text"])
    check("deshaw apply url", jobs[0]["job_url"].endswith("/recruit/jobs/Ads/Link/Core-Tech-Principal-Manager-Tech-Treasury-Tech-6760"))


def test_intouchcx_feed_filters_india_and_maps_ids() -> None:
    payload = {
        "jobs": [
            {
                "job": "Customer Service Representative",
                "link": "https://apply.intouchcx.com/3",
                "location": "Mesa, Arizona, United States",
            },
            {
                "job": "Customer Service Associate Voice",
                "link": "https://apply.intouchcx.com/153",
                "location": "Bengaluru, India",
            },
            {
                "job": "Full Stack Developer ",
                "link": "https://jobs.dayforcehcm.com/en-CA/intouchcx/CANDIDATEPORTAL/jobs/10082",
                "location": "Hyderabad, India",
            },
        ]
    }
    jobs = parse_intouchcx_feed(
        payload,
        {
            "company": "IntouchCX",
            "endpoint": "https://www.intouchcx.com/wp-json/intouchcx/v1/jobs?country=India",
            "industry": "Customer Experience",
            "india_only": True,
        },
    )
    check("intouchcx india count", len(jobs) == 2)
    check("intouchcx legacy id", jobs[0]["job_id"] == "intouchcx-apply-153")
    check("intouchcx dayforce id", jobs[1]["job_id"] == "intouchcx-dayforce-10082")
    check("intouchcx title stripped", jobs[1]["title"] == "Full Stack Developer")
    check("intouchcx source platform", jobs[1]["source_platform"] == "IntouchCX")


def test_intouchcx_legacy_detail_extracts_application_body() -> None:
    html = """
    <div class="application-body in" style="font-family: Poppins;">
      <p><strong>About the Job</strong></p>
      <p>We are looking for a customer support associate.</p>
      <ul><li>Handle customer calls end to end.</li></ul>
    </div>
    <div class="application-buttons text-center"></div>
    """
    text = parse_legacy_intouchcx_detail(html)
    check("intouchcx legacy jd text", "customer support associate" in text)
    check("intouchcx legacy jd list text", "Handle customer calls" in text)


def test_intouchcx_dayforce_next_data_extracts_detail() -> None:
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "jobData": {
            "jobPostingId": 10082,
            "jobTitle": "Full Stack Developer ",
            "postingStartTimestampUTC": "2025-05-28T08:00:00+00:00",
            "jobPostingContent": {
              "jobDescriptionHeader": "<p><strong>About IntouchCX</strong></p>",
              "jobDescription": "<p>We are seeking a Full Stack Developer.</p><ul><li>Must have Angular experience.</li></ul>",
              "jobDescriptionFooter": null
            },
            "postingLocations": [
              {
                "formattedAddress": "Hyderabad, Telangana, India",
                "cityName": "Hyderabad",
                "isoCountryCode": "IN"
              }
            ],
            "jobPostingAttributes": [
              {"name": "PayType", "value": "Salary"}
            ]
          }
        }
      }
    }
    </script>
    """
    detail = parse_dayforce_next_data(html)
    check("intouchcx dayforce title", detail["title"] == "Full Stack Developer")
    check("intouchcx dayforce jd", "Angular experience" in detail["raw_jd_text"])
    check("intouchcx dayforce location", detail["location_city"] == "Hyderabad, Telangana, India")
    check("intouchcx dayforce date", detail["date_posted"] == "2025-05-28T08:00:00+00:00")


def test_google_careers_html_parser_maps_embedded_jobs() -> None:
    html = r'''
    <script>
    AF_initDataCallback({key: 'ds:1', hash: '2', data:[[[
      ["107743710602502854","Senior Security Architect, Mandiant, Google Cloud (English)",
       "https://www.google.com/about/careers/applications/signin?jobId=abc&loc=IN&title=Senior+Security+Architect",
       [null,"<ul><li>Identify solution issue trends.</li></ul>"],
       [null,"<h3>Minimum qualifications:</h3><ul><li>Bachelor's degree.</li></ul>"],
       "projects/gweb-careers-proto/tenants/60107626/companies/google",null,"Google","en-US",
       [["India",["India"],null,null,null,"IN"]],
       [null,"<p>Work on client security engagements.</p>"],
       [2],[1778142684,3000000],[1778142684,3000000],[1778142684,224000000],
       [null,""],1,null,[null,"<b>Remote location: India.</b>"],
       [null,"<ul><li>Bachelor's degree.</li></ul>"],2],
      ["999","US Role","https://www.google.com/about/careers/applications/signin?jobId=us",
       [null,"<ul><li>US responsibility.</li></ul>"],[null,"<ul><li>US qualification.</li></ul>"],
       "",null,"Google","en-US",[["New York, NY, USA",["New York"],"New York",null,"NY","US"]],
       [null,"<p>US overview.</p>"],[2],[1778142684,0],[1778142684,0],[1778142684,0],
       [null,""],1,null,[null,""],[null,""],2]
    ]]], sideChannel: {}});
    </script>
    '''
    jobs = parse_google_careers_html(
        html,
        {
            "company": "Google",
            "endpoint": "https://www.google.com/about/careers/applications/jobs/results/?location=India",
            "industry": "Technology",
            "india_only": True,
        },
    )
    check("google parser filters india", len(jobs) == 1)
    check("google native id", jobs[0]["job_id"] == "107743710602502854")
    check("google title", jobs[0]["title"] == "Senior Security Architect, Mandiant, Google Cloud (English)")
    check("google location", jobs[0]["location_city"] == "India")
    check("google jd overview", "Work on client security engagements" in jobs[0]["raw_jd_text"])
    check("google jd responsibilities", "Identify solution issue trends" in jobs[0]["raw_jd_text"])
    check("google date", jobs[0]["date_posted"] == "2026-05-07")


def test_microsoft_pcsx_search_parser_maps_india_positions() -> None:
    payload = {
        "status": 200,
        "data": {
            "count": 2,
            "positions": [
                {
                    "id": 1970393556856063,
                    "displayJobId": "200033959",
                    "atsJobId": "200033959",
                    "name": "Senior Software Engineer",
                    "locations": ["India, Multiple Locations, Multiple Locations"],
                    "postedTs": 1776326224,
                    "department": "Software Engineering",
                    "positionUrl": "/careers/job/1970393556856063",
                },
                {
                    "id": 1970393556000000,
                    "displayJobId": "200000001",
                    "name": "US Engineer",
                    "locations": ["Redmond, Washington, United States"],
                    "positionUrl": "/careers/job/1970393556000000",
                },
            ],
        },
    }
    jobs = parse_microsoft_search_payload(
        payload,
        {
            "company": "Microsoft",
            "endpoint": "https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&location=India",
            "industry": "Technology",
            "india_only": True,
        },
    )
    check("microsoft parser filters india", len(jobs) == 1)
    check("microsoft search native id", jobs[0]["job_id"] == "microsoft-200033959")
    check("microsoft search title", jobs[0]["title"] == "Senior Software Engineer")
    check("microsoft search location", jobs[0]["location_city"] == "India, Multiple Locations, Multiple Locations")
    check("microsoft search date", jobs[0]["date_posted"] == "2026-04-16")
    check("microsoft search url", jobs[0]["job_url"].endswith("/careers/job/1970393556856063?hl=en"))


def test_microsoft_detail_parser_maps_full_jd() -> None:
    payload = {
        "id": 1970393556864810,
        "name": "Site Reliability Engineer 2",
        "posting_name": "Site Reliability Engineer 2",
        "location": "India, Telangana, Hyderabad",
        "locations": ["India, Telangana, Hyderabad"],
        "department": "Service Engineering",
        "business_unit": "Cloud + AI",
        "t_update": 1778477142,
        "ats_job_id": "200037078",
        "display_job_id": "200037078",
        "job_description": "<b>Overview</b><br><p>Build reliable cloud services.</p>",
    }
    detail = parse_microsoft_detail_payload(payload)
    check("microsoft detail id", detail["job_id"] == "microsoft-200037078")
    check("microsoft detail title", detail["title"] == "Site Reliability Engineer 2")
    check("microsoft detail jd", "Build reliable cloud services" in detail["raw_jd_text"])
    check("microsoft detail location", detail["location_city"] == "India, Telangana, Hyderabad")
    check("microsoft detail business unit", detail["business_unit"] == "Cloud + AI")
    check("microsoft detail date", detail["date_posted"] == "2026-05-11")


def test_hilabs_html_parser_maps_india_jobs() -> None:
    html = r'''
    <script>
    self.__next_f.push([1,"24:[\"$\",\"$f\",null,{\"fallback\":[\"$\",\"div\",null,{}],\"children\":[\"$\",\"$L25\",null,{\"countByDepartmentAndCountry\":{\"india\":{\"All Job Listing\":1},\"usa\":{\"All Job Listing\":1}},\"groupedByPlaceAndDepartments\":{\"india\":{\"All Job Listing\":[{\"id\":27,\"documentId\":\"n1q35av2zmlmrfzi8mfowhmg\",\"Add_description_to_Hilabs_Team\":\"We are seeking a Lead Data Scientist.\",\"Job_Id\":null,\"Job_Title\":\"Lead Data Scientist\",\"Category\":\"Data Science\",\"Job_Location\":\"Pune, Maharashtra, India\",\"createdAt\":\"2025-08-26T11:56:09.834Z\",\"updatedAt\":\"2025-08-26T11:56:16.565Z\",\"publishedAt\":\"2025-08-26T11:56:16.594Z\",\"Job_Description\":[{\"id\":53,\"Heading\":\"Responsibilities\",\"Add_bullet_points_with_heading\":[{\"id\":55,\"Heading\":null,\"Points\":[{\"id\":557,\"Point\":\"Build machine learning algorithms.\"},{\"id\":558,\"Point\":\"Deploy big data workflows.\"}]}]},{\"id\":54,\"Heading\":\"Desired Profile\",\"Add_bullet_points_with_heading\":[{\"id\":56,\"Heading\":null,\"Points\":[{\"id\":568,\"Point\":\"Strong Python skills.\"}]}]}],\"Screening_Questions\":[]}]} ,\"usa\":{\"All Job Listing\":[{\"id\":1,\"documentId\":\"us-role\",\"Add_description_to_Hilabs_Team\":\"US only role\",\"Job_Title\":\"US Data Scientist\",\"Category\":\"Data Science\",\"Job_Location\":\"Austin, Texas, United States\",\"updatedAt\":\"2025-08-27T00:00:00.000Z\",\"Job_Description\":[]}]}},\"tagItems\":{\"india\":[{\"title\":\"All Job Listing\"}],\"usa\":[{\"title\":\"All Job Listing\"}]}}]}]"])\n
    </script>
    '''
    jobs = parse_hilabs_html(
        html,
        {
            "company": "HiLabs",
            "endpoint": "https://www.hilabs.com/careers/all-open-positions?location=india",
            "industry": "Healthcare Technology",
            "india_only": True,
        },
    )
    check("hilabs filters india", len(jobs) == 1)
    check("hilabs id", jobs[0]["job_id"] == "hilabs-n1q35av2zmlmrfzi8mfowhmg")
    check("hilabs title", jobs[0]["title"] == "Lead Data Scientist")
    check("hilabs location", jobs[0]["location_city"] == "Pune, Maharashtra, India")
    check("hilabs jd intro", "Lead Data Scientist" in jobs[0]["raw_jd_text"])
    check("hilabs jd bullet", "Build machine learning algorithms" in jobs[0]["raw_jd_text"])
    check("hilabs date", jobs[0]["date_posted"] == "2025-08-26")
    check("hilabs url", jobs[0]["job_url"].endswith("/careers/all-open-positions/Lead-Data-Scientist/n1q35av2zmlmrfzi8mfowhmg"))


def test_blackbrix_listing_and_detail_parsers() -> None:
    listing_html = """
    <div class="awsm-job-listings awsm-row awsm-grid-col-3" data-listings="18">
      <div class="awsm-job-listing-item awsm-grid-item" id="awsm-grid-item-12225">
        <a href="https://blackbrix.com/jobs/economist/" class="awsm-job-item">
          <div class="awsm-grid-left-col">
            <h2 class="awsm-job-post-title">Economist</h2>
          </div>
          <div class="awsm-grid-right-col">
            <div class="awsm-job-specification-wrapper">
              <div class="awsm-job-specification-item awsm-job-specification-job-location">
                <span class="awsm-job-specification-term">Kolkata West Bengal</span>
              </div>
            </div>
          </div>
        </a>
      </div>
    </div>
    """
    items = parse_blackbrix_listing_items(listing_html, "https://blackbrix.com/job-openings/")
    check("blackbrix listing count", len(items) == 1)
    check("blackbrix listing id", items[0]["job_id"] == "12225")
    check("blackbrix listing title", items[0]["title"] == "Economist")
    check("blackbrix listing location", items[0]["location_city"] == "Kolkata West Bengal")

    detail_html = """
    <body class="single single-awsm_job_openings postid-12225">
      <div class="awsm-job-content">
        <div class="awsm-job-entry-content entry-content">
          <p><strong>About Us</strong></p>
          <p>Black Brix is a management consultancy firm.</p>
          <p><strong>Base Location - Kolkata, West Bengal</strong></p>
          <p><strong>Responsibility.</strong><br>Conduct advanced economic analysis.<br>Translate complex findings into recommendations.</p>
          <p><strong>Desired Candidate Profile</strong><br>Master's degree in Economics.<br>Strong analytical skills.</p>
        </div>
      </div>
      <div class="awsm-job-specification-wrapper">
        <div class="awsm-job-specification-item awsm-job-specification-job-category">
          <span class="awsm-job-specification-term">Economist</span>
        </div>
        <div class="awsm-job-specification-item awsm-job-specification-job-type">
          <span class="awsm-job-specification-term">Full Time</span>
        </div>
        <div class="awsm-job-specification-item awsm-job-specification-job-location">
          <span class="awsm-job-specification-term">Kolkata West Bengal</span>
        </div>
      </div>
      <div class="awsm-job-form">
        <h2>Apply for this position</h2>
      </div>
    </body>
    """
    detail = parse_blackbrix_detail(detail_html, "https://blackbrix.com/jobs/economist/")
    check("blackbrix detail id", detail["job_id"] == "12225")
    check("blackbrix detail title", detail["title"] == "Economist")
    check("blackbrix detail location", detail["location_city"] == "Kolkata West Bengal")
    check("blackbrix detail jd", "advanced economic analysis" in detail["raw_jd_text"])
    check("blackbrix detail apply url", detail["job_url"] == "https://blackbrix.com/jobs/economist/")


def test_ashby_job_board_parser_maps_description_plain() -> None:
    payload = {
        "jobs": [
            {
                "id": "snow-1",
                "title": "Senior Solution Engineer",
                "department": "Solution Engineering",
                "location": "IN-Bangalore-MSO",
                "secondaryLocations": [],
                "publishedAt": "2026-05-20T00:00:00.000+00:00",
                "jobUrl": "https://jobs.ashbyhq.com/snowflake/snow-1",
                "applyUrl": "https://jobs.ashbyhq.com/snowflake/snow-1/application",
                "descriptionPlain": "Build data cloud solutions for enterprise customers.",
            },
            {
                "id": "snow-us",
                "title": "US Role",
                "department": "Sales",
                "location": "New York, United States",
                "descriptionPlain": "US-only role.",
            },
            {
                "id": "india-title",
                "title": "Senior Solutions Architect - India",
                "department": "Solutions",
                "location": "APAC | Remote",
                "descriptionPlain": "Support customers across the India market.",
            },
        ]
    }
    jobs = parse_ashby_job_board(
        payload,
        {
            "company": "Snowflake",
            "endpoint": "https://api.ashbyhq.com/posting-api/job-board/snowflake",
            "industry": "Technology",
            "india_only": True,
        },
    )
    check("ashby filters india", len(jobs) == 2)
    check("ashby title", jobs[0]["title"] == "Senior Solution Engineer")
    check("ashby jd", "data cloud solutions" in jobs[0]["raw_jd_text"])
    check("ashby apply url", jobs[0]["job_url"].endswith("/application"))
    check("ashby title country signal", jobs[1]["location_city"] == "APAC | Remote | India")


def test_trakstar_listing_fetches_detail_and_filters_india() -> None:
    listing_html = """
    <div class="js-card list-item js-careers-page-job-list-item" data-href="/jobs/fk0zvkx/">
      <h3 class="js-job-list-opening-name">AI Product Manager 2 : 19487</h3>
      <div class="js-job-list-opening-loc">Bengaluru, Karnataka, India</div>
      <div class="col-md-4"><div class="rb-text-4">Product</div></div>
    </div>
    <div class="js-card list-item js-careers-page-job-list-item" data-href="/jobs/us123/">
      <h3 class="js-job-list-opening-name">US Role</h3>
      <div class="js-job-list-opening-loc">San Francisco, California, United States</div>
    </div>
    """
    detail_html = """
    <main>
      <a>Back to all openings</a>
      <span>See all the jobs at Whatfix here:</span>
      <a>http://whatfix101.recruiterbox.com/jobs</a>
      <div class="js-job-title">AI Product Manager 2 : 19487</div>
      <div>Bengaluru, Karnataka, India</div>
      <span>|</span>
      <div>Product</div>
      <section>
        <h2>Who are we?</h2>
        <p>Whatfix builds digital adoption products.</p>
        <h2>Role</h2>
        <p>Own AI roadmap and work with engineering.</p>
      </section>
      <button>Apply</button>
    </main>
    """

    original_fetch_detail = trakstar._fetch_detail
    trakstar._fetch_detail = lambda url: detail_html
    try:
        jobs = trakstar.parse_trakstar_listing(
            listing_html,
            {
                "company": "Whatfix",
                "endpoint": "https://whatfix101.hire.trakstar.com/",
                "industry": "Technology",
                "india_only": True,
            },
        )
    finally:
        trakstar._fetch_detail = original_fetch_detail

    check("trakstar filters india", len(jobs) == 1)
    check("trakstar id", jobs[0]["job_id"] == "fk0zvkx")
    check("trakstar title", jobs[0]["title"] == "AI Product Manager 2 : 19487")
    check("trakstar jd", "digital adoption products" in jobs[0]["raw_jd_text"])
    check("trakstar location", jobs[0]["location_city"] == "Bengaluru, Karnataka, India")


def test_rippling_listing_and_detail_next_data_parse() -> None:
    listing_html = """
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "jobs": {
            "items": [
              {
                "id": "rip-1",
                "name": "Customer Support Manager - HRIS",
                "url": "https://ats.rippling.com/rippling/jobs/rip-1",
                "department": {"name": "HRIS Support"},
                "locations": [{"name": "Bangalore, India", "country": "India", "countryCode": "IN"}],
                "language": "en-US"
              },
              {
                "id": "rip-us",
                "name": "US Role",
                "url": "https://ats.rippling.com/rippling/jobs/rip-us",
                "department": {"name": "Sales"},
                "locations": [{"name": "New York, United States", "countryCode": "US"}]
              }
            ]
          }
        }
      }
    }
    </script>
    """
    listing_jobs = parse_rippling_listing_page(
        listing_html,
        {"company": "Rippling", "endpoint": "https://www.rippling.com/careers/open-roles", "industry": "Technology"},
    )
    check("rippling filters india listing", len(listing_jobs) == 1)
    check("rippling listing title", listing_jobs[0]["title"] == "Customer Support Manager - HRIS")
    check("rippling listing location", listing_jobs[0]["location_city"] == "Bangalore, India")

    detail_html = """
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "apiData": {
            "jobPost": {
              "uuid": "rip-1",
              "name": "Customer Support Manager - HRIS",
              "description": {
                "company": "<p>About Rippling</p>",
                "job": "<p>Lead HRIS support teams.</p>"
              },
              "workLocations": ["Bangalore, India"],
              "department": {"name": "HRIS Support"},
              "employmentType": {"id": "Salaried, full-time"},
              "createdOn": "2026-05-19T08:47:28.158000-07:00",
              "url": "https://ats.rippling.com/rippling/jobs/rip-1"
            }
          }
        }
      }
    }
    </script>
    """
    detail = parse_rippling_detail_page(detail_html, "https://ats.rippling.com/rippling/jobs/rip-1", {"industry": "Technology"})
    check("rippling detail id", detail["job_id"] == "rip-1")
    check("rippling detail jd", "Lead HRIS support teams." in detail["raw_jd_text"])
    check("rippling detail department", detail["business_unit"] == "HRIS Support")


def test_rippling_listing_dehydrated_state_parse() -> None:
    listing_html = """
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "dehydratedState": {
            "queries": [
              {
                "state": {
                  "data": {
                    "items": [
                      {
                        "id": "sanas-in",
                        "name": "Senior Product Designer",
                        "url": "https://ats.rippling.com/sanas/jobs/sanas-in",
                        "department": {"name": "Product"},
                        "locations": [
                          {
                            "name": "Bengaluru, India",
                            "country": "India",
                            "countryCode": "IN"
                          }
                        ]
                      },
                      {
                        "id": "sanas-us",
                        "name": "US Role",
                        "url": "https://ats.rippling.com/sanas/jobs/sanas-us",
                        "locations": [
                          {
                            "name": "Palo Alto, United States",
                            "countryCode": "US"
                          }
                        ]
                      }
                    ]
                  }
                }
              }
            ]
          }
        }
      }
    }
    </script>
    """
    jobs = parse_rippling_listing_page(
        listing_html,
        {
            "company": "Sanas",
            "endpoint": "https://ats.rippling.com/sanas/jobs",
            "industry": "Technology",
        },
    )
    check("rippling dehydrated state filters india", len(jobs) == 1)
    check("rippling dehydrated state title", jobs[0]["title"] == "Senior Product Designer")


def test_workline_listing_and_detail_parse() -> None:
    try:
        from providers.workline import parse_workline_detail_html, parse_workline_listing_payload
    except ImportError as exc:
        raise AssertionError("workline provider is missing") from exc

    payload = {
        "d": {
            "obj1": json.dumps([
                {
                    "Req_No": "3775",
                    "Position_Name": "Relationship Manager",
                    "PublishDate": "04-Jun-2026",
                    "SearchKeyWord": "Relationship-Manager-Job-in-Borivali-2778",
                    "Country_Name": "India",
                    "City_Name": "Mumbai",
                    "Field1": "Assistant Manager",
                    "Field2": "Mumbai",
                    "TrackToken": "c32601d9-735b-468a-9a5c-797b3635b42b",
                    "FunctionName": "Retail Sales",
                }
            ]),
            "obj2": "[]",
        }
    }
    portal = {
        "company": "SBI Mutual Fund",
        "endpoint": "https://app1397.workline.hr/Cportal/GeneralOpening.aspx",
        "industry": "Financial Services",
        "india_only": True,
    }
    jobs = parse_workline_listing_payload(payload, portal)
    check("workline listing count", len(jobs) == 1)
    check("workline listing id", jobs[0]["job_id"] == "3775")
    check("workline listing title", jobs[0]["title"] == "Relationship Manager")
    check("workline listing location", jobs[0]["location_city"] == "Mumbai")
    check(
        "workline listing detail url",
        jobs[0]["job_url"].endswith(
            "/CandidatePortal/c32601d9-735b-468a-9a5c-797b3635b42b/"
            "Relationship-Manager-Job-in-Borivali-2778"
        ),
    )

    detail_html = """
    <div class="jobs-wrapper"><div class="summary">Job summary card</div></div>
    <main>
      <h1>Relationship Manager</h1>
      <div class="job-info">
        <span>3775</span><span>PDM - Domestic Business</span>
        <span>Borivali</span><span>04-Jun-2026</span>
      </div>
      <div class="jobs-wrapper">
        <section class="description-info">
          <h2>Roles &amp; Responsibilities</h2>
          <p>Build and manage distributor relationships.</p>
          <p>Own the regional sales plan.</p>
        </section>
      </div>
      <a href="/Candidate/SignInv1.aspx">Apply</a>
    </main>
    """
    detail = parse_workline_detail_html(detail_html, jobs[0]["job_url"], portal)
    check("workline detail jd", "distributor relationships" in detail["raw_jd_text"])


def test_peoplestrong_listing_payload_parse() -> None:
    try:
        from providers.peoplestrong import parse_peoplestrong_listing_payload
    except ImportError as exc:
        raise AssertionError("peoplestrong provider is missing") from exc

    payload = {
        "totalRecords": 1,
        "response": [
            {
                "jobPostedDate": "2026-05-27",
                "locationHierarchyComplete": "India>Maharashtra>Mumbai>Corporate Office",
                "jobDetailUrl": (
                    "https://lodhacareers.peoplestrong.com/job/detail/"
                    "LOG_D-S-ID_1715990"
                ),
                "requisitionId": 1715990,
                "jobTitle": "Design - Support - Interior Design",
                "jobCode": "LOG/D-S-ID/1715990",
                "organizationUnit": "Design",
                "skills": {
                    "mustTohave": ["Interior Design"],
                    "goodtohave": ["Interior Architecture"],
                },
            }
        ],
    }
    jobs = parse_peoplestrong_listing_payload(
        payload,
        {
            "company": "Lodha Group",
            "endpoint": "https://lodhacareers.peoplestrong.com",
            "industry": "Real Estate",
            "india_only": True,
        },
    )
    check("peoplestrong listing count", len(jobs) == 1)
    check("peoplestrong listing id", jobs[0]["job_id"] == "1715990")
    check("peoplestrong listing title", jobs[0]["title"] == "Design - Support - Interior Design")
    check("peoplestrong listing location", jobs[0]["location_city"] == "Corporate Office")
    check("peoplestrong listing source", jobs[0]["source_platform"] == "PeopleStrong")


def test_ubs_brassring_embedded_results_parse() -> None:
    try:
        from providers.ubs_brassring import parse_ubs_search_html
    except ImportError as exc:
        raise AssertionError("ubs brassring provider is missing") from exc

    payload = {
        "HotJobs": {
            "Job": [
                {
                    "Questions": [
                        {"QuestionName": "reqid", "ActualValueFromSolar": "344751"},
                        {"QuestionName": "jobtitle", "ActualValueFromSolar": "CA Intern"},
                        {"QuestionName": "formtext23", "ActualValueFromSolar": "India"},
                        {
                            "QuestionName": "jobdescription",
                            "ActualValueFromSolar": "<p>Support finance and risk projects.</p>",
                        },
                        {
                            "QuestionName": "lastupdated",
                            "ActualValueFromSolar": "2026-06-10T00:00:00Z",
                        },
                    ],
                    "Link": (
                        "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?"
                        "partnerid=25008&siteid=5012&PageType=JobDetails&jobid=344751"
                    ),
                },
                {
                    "Questions": [
                        {"QuestionName": "reqid", "ActualValueFromSolar": "us-1"},
                        {"QuestionName": "jobtitle", "ActualValueFromSolar": "US Role"},
                        {
                            "QuestionName": "formtext23",
                            "ActualValueFromSolar": "United States - New York",
                        },
                    ],
                    "Link": "https://jobs.ubs.com/us-1",
                },
            ]
        },
        "TotalCount": 2,
    }
    encoded = (
        json.dumps(payload)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    html = f'<input id="searchResults" type="hidden" value="{encoded}" />'
    jobs = parse_ubs_search_html(
        html,
        {
            "company": "UBS",
            "endpoint": "https://jobs.ubs.com/TGnewUI/Search/Home/Home",
            "industry": "Financial Services",
            "india_only": True,
        },
    )
    check("ubs embedded results filters india", len(jobs) == 1)
    check("ubs embedded results id", jobs[0]["job_id"] == "344751")
    check("ubs embedded results title", jobs[0]["title"] == "CA Intern")
    check("ubs embedded results jd", "finance and risk projects" in jobs[0]["raw_jd_text"])


def test_bdo_map_links_keep_only_job_details() -> None:
    try:
        from providers.bdo_firecrawl import parse_bdo_api_payload, parse_bdo_map_links
    except ImportError as exc:
        raise AssertionError("bdo firecrawl provider is missing") from exc

    links = [
        {
            "url": "https://www.bdo.in/en-gb/careers/new-job-openings",
            "title": "New Job Openings",
            "description": "BDO India jobs.",
        },
        {
            "url": (
                "https://www.bdo.in/en-gb/careers/new-job-openings"
                "?careerJobTitle=Manager"
            ),
            "title": "Managers",
            "description": "",
        },
        {
            "url": (
                "https://www.bdo.in/en-gb/careers/new-job-openings/"
                "manager-digital-transformation-ts-mum-0130"
            ),
            "title": "Manager - Digital Transformation",
            "description": "Lead digital transformation engagements.",
        },
    ]
    jobs = parse_bdo_map_links(
        links,
        {
            "company": "BDO India",
            "endpoint": "https://www.bdo.in/en-gb/careers/new-job-openings",
            "industry": "Professional Services",
        },
    )
    check("bdo map keeps detail only", len(jobs) == 1)
    check("bdo map title", jobs[0]["title"] == "Manager - Digital Transformation")
    check("bdo map stable slug id", jobs[0]["job_id"] == "manager-digital-transformation-ts-mum-0130")

    api_jobs = parse_bdo_api_payload(
        {
            "data": [
                {
                    "publishDate": "2026-05-07T09:12:03",
                    "applyURL": "/en-gb/careers/new-job-openings/associate-manager-bdg-3271-technology-services",
                    "title": "Associate Manager - BDG/3271 - Technology Services",
                    "jobTitle": "Manager",
                    "reference": "BDG/3271",
                    "level": "Experienced",
                    "locations": ["Mumbai"],
                }
            ],
            "totalCount": 1,
        },
        {
            "company": "BDO India",
            "endpoint": "https://www.bdo.in/en-gb/careers/new-job-openings",
            "industry": "Professional Services",
        },
    )
    check("bdo api job count", len(api_jobs) == 1)
    check("bdo api stable reference", api_jobs[0]["job_id"] == "BDG/3271")
    check("bdo api apply url", api_jobs[0]["job_url"].endswith("/associate-manager-bdg-3271-technology-services"))
    check("bdo api metadata text", "Experienced" in api_jobs[0]["raw_jd_text"])


def test_cornerstone_search_and_detail_payloads_map_india_jobs() -> None:
    portal = {
        "company": "Simon-Kucher & Partners",
        "endpoint": "https://simon-kucher.csod.com/ux/ats/careersite/6/home/?c=simon-kucher",
        "industry": "Consulting",
        "india_only": True,
    }
    payload = {
        "data": {
            "requisitions": [
                {
                    "requisitionId": 4209,
                    "displayJobTitle": "Consultant",
                    "postingEffectiveDate": "6/10/2026",
                    "locations": [{"city": "Mumbai", "state": "Maharashtra", "country": "IN"}],
                },
                {
                    "requisitionId": 4210,
                    "displayJobTitle": "US Consultant",
                    "locations": [{"city": "Boston", "state": "MA", "country": "US"}],
                },
            ]
        }
    }
    jobs = parse_cornerstone_search_payload(payload, portal)
    check("cornerstone filters india", len(jobs) == 1)
    check("cornerstone id", jobs[0]["job_id"] == "4209")
    check("cornerstone title", jobs[0]["title"] == "Consultant")
    check("cornerstone location", jobs[0]["location_city"] == "Mumbai, Maharashtra, India")

    detail = {
        "data": {
            "displayTitle": "Consultant",
            "externalDescription": "<p>Advise clients on pricing strategy.</p>",
            "ref": "SKP-4209",
            "primaryLocation": {"city": "Mumbai", "state": "Maharashtra", "country": "IN"},
        }
    }
    merged = merge_cornerstone_detail(jobs[0], detail)
    check("cornerstone detail jd", merged["raw_jd_text"] == "Advise clients on pricing strategy.")
    check("cornerstone detail ref", merged["job_id"] == "SKP-4209")


def test_virtusa_map_and_markdown_parsers_create_stable_jobs() -> None:
    from providers.virtusa_firecrawl import (
        merge_virtusa_markdown,
        parse_virtusa_map_links,
    )

    links = [
        {
            "url": "https://www.virtusa.com/careers/in/hyderabad/salesforce",
            "title": "Salesforce - Virtusa",
            "description": "Browse Salesforce roles.",
        },
        {
            "url": (
                "https://www.virtusa.com/careers/job-search/in/bangalore/"
                "sales-and-marketing/ui-designer/job-255803"
            ),
            "title": "job-255803 - UI Designer - Virtusa",
            "description": "Apply for job with Virtusa in Bangalore, India.",
        },
        {
            "url": (
                "https://www.virtusa.com/careers/in/hyderabad/"
                "data-platforms/gcp-data-engineer/creq259311"
            ),
            "title": "GCP Data Engineer - Virtusa",
            "description": "Apply for job with Virtusa in Hyderabad, India.",
        },
    ]
    jobs = parse_virtusa_map_links(
        links,
        {
            "company": "Virtusa",
            "endpoint": "https://www.virtusa.com/careers",
            "industry": "IT Services",
            "india_only": True,
        },
    )
    check("virtusa map keeps job details", len(jobs) == 2)
    check("virtusa stable job id", jobs[0]["job_id"] == "job-255803")
    check("virtusa title cleaned", jobs[0]["title"] == "UI Designer")
    check("virtusa location from path", jobs[0]["location_city"] == "Bangalore, India")

    markdown = """
    # UI Designer

    Location: Bangalore, Karnataka, India

    Date Posted: 08/04/2026

    ## Job description

    Create high-fidelity Figma prototypes and accessible dashboards.

    ## Qualifications

    Two years of product design experience.
    """
    merged = merge_virtusa_markdown(jobs[0], markdown)
    check("virtusa markdown jd", "high-fidelity Figma prototypes" in merged["raw_jd_text"])
    check("virtusa markdown location", merged["location_city"] == "Bangalore, Karnataka, India")
    check("virtusa markdown date", merged["date_posted"] == "08/04/2026")


def test_dejobs_rss_parser_maps_india_items() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><title>Jobs in India</title>
      <item>
        <title>(IND-Bangalore) Member of Technical Staff 3</title>
        <link>https://nutanix.dejobs.org/47E0CF75426341A5B4959DF24D97D6F225</link>
        <description><![CDATA[<p>Build distributed systems.</p>]]></description>
        <pubDate>Tue, 19 May 2026 07:19:44 -0400</pubDate>
        <guid>https://nutanix.dejobs.org/47E0CF75426341A5B4959DF24D97D6F225</guid>
      </item>
      <item>
        <title>(US-San Jose) US Role</title>
        <link>https://nutanix.dejobs.org/us-role</link>
        <description>US-only role.</description>
      </item>
    </channel></rss>
    """
    jobs = parse_dejobs_rss(
        rss,
        {"company": "Nutanix", "endpoint": "https://nutanix.dejobs.org/jobs/feed/rss?location=India", "industry": "Technology"},
    )
    check("dejobs filters india", len(jobs) == 1)
    check("dejobs title cleaned", jobs[0]["title"] == "Member of Technical Staff 3")
    check("dejobs location", jobs[0]["location_city"] == "Bangalore, India")
    check("dejobs jd", jobs[0]["raw_jd_text"] == "Build distributed systems.")


def test_talent500_parser_fetches_detail_and_filters_india() -> None:
    payload = {
        "data": [
            {
                "id": 101,
                "title": "Data Engineer",
                "company": {"name": "Costco Wholesale"},
                "location": "Hyderabad",
                "country": {"name": "India"},
                "slug": "data-engineer-101",
            },
            {
                "id": 202,
                "title": "US Role",
                "company": {"name": "Costco Wholesale"},
                "location": "Seattle",
                "country": {"name": "United States"},
            },
        ]
    }

    original_fetch_detail = talent500._fetch_detail
    talent500._fetch_detail = lambda item: {
        "job_code": f"costco-{item['id']}",
        "title_alias_1": item["title"],
        "role_summary": "<p>Build ecommerce data platforms.</p>",
        "job_url": f"https://talent500.com/jobs/costco/{item['id']}/",
    }
    try:
        jobs = talent500.parse_talent500_jobs(
            payload,
            {
                "company": "Costco Wholesale",
                "endpoint": "https://prod-warmachine.talent500.co/api/jobs/?company_slug=costco",
                "industry": "Retail Technology",
                "india_only": True,
                "talent500_company_slug": "costco",
            },
        )
    finally:
        talent500._fetch_detail = original_fetch_detail

    check("talent500 filters india", len(jobs) == 1)
    check("talent500 id", jobs[0]["job_id"] == "costco-101")
    check("talent500 title", jobs[0]["title"] == "Data Engineer")
    check("talent500 jd", "ecommerce data platforms" in jobs[0]["raw_jd_text"])
    check("talent500 company", jobs[0]["company_name"] == "Costco Wholesale")


def test_sap_jobs2web_accepts_bare_in_country_token() -> None:
    from providers.sap_jobs2web_html import _is_india_listing_location

    check("sap bare IN is India", _is_india_listing_location("IN"))
    check("sap repeated IN is India", _is_india_listing_location("IN IN"))
    check("sap city comma IN is India", _is_india_listing_location("Mumbai, IN"))
    check("sap Indiana is not India", not _is_india_listing_location("Indianapolis, Indiana, United States"))


def test_ripplehire_jobvolist_and_detail_payload_map_to_job() -> None:
    from providers.ripplehire import _extract_listing_docs, _merge_detail_payload, _doc_to_job

    payload = {
        "jobVoList": [
            {
                "jobSeq": 640454,
                "jobTitle": "Manager Mining",
                "locations": ["West Bokaro"],
                "departmentName": "Operations",
            }
        ],
        "totalJobCount": 31,
    }
    docs = _extract_listing_docs(payload)
    detail_payload = {
        "jobVO": {
            "jobSeq": 640454,
            "jobDesc": "<p>Lead mining operations and safety systems.</p>",
            "location": "West Bokaro",
            "jobTitle": "Manager Mining",
        }
    }
    merged = _merge_detail_payload(docs[0], detail_payload)
    job = _doc_to_job(
        merged,
        {
            "company": "Tata Steel",
            "industry": "Industrial",
            "india_only": True,
        },
        "https://tatasteel.ripplehire.com",
        "https://tatasteel.ripplehire.com/candidate/candidatejobsearch",
    )

    check("ripplehire jobVoList docs parsed", len(docs) == 1)
    check("ripplehire jobSeq id", job["job_id"] == "640454")
    check("ripplehire title", job["title"] == "Manager Mining")
    check("ripplehire detail jd", job["raw_jd_text"] == "Lead mining operations and safety systems.")
    check("ripplehire detail url", "candidatejobdetail" in job["job_url"])
    check("ripplehire location", job["location_city"] == "West Bokaro")


def test_zoho_recruit_builds_company_specific_apply_url() -> None:
    from providers.zoho_recruit import _build_apply_url, _parse_embedded_jobs

    url = _build_apply_url(
        {
            "endpoint": "https://careers.npci.org.in/jobs/Careers",
            "zoho_page_id": "190737000000336688",
        },
        "190737000001308027",
    )
    check("zoho npci apply host", url.startswith("https://careers.npci.org.in/recruit/SingleJobDetail.na"))
    check("zoho npci sys id", "sys_id=190737000001308027" in url)
    check("zoho npci page id", "page_id=190737000000336688" in url)

    html = """
    <input type="hidden" id="jobs" value='[{&quot;Posting_Title&quot;:&quot;Senior Associate Data Science&quot;,&quot;City&quot;:&quot;Hyderabad&quot;,&quot;Country&quot;:&quot;India&quot;,&quot;Job_Description&quot;:&quot;Build data products&quot;,&quot;id&quot;:&quot;190737000001308027&quot;}]'>
    """
    jobs = _parse_embedded_jobs(html)
    check("zoho hidden jobs parsed", len(jobs) == 1)
    check("zoho hidden title", jobs[0]["Posting_Title"] == "Senior Associate Data Science")


def test_juspay_astro_parser_maps_embedded_india_jobs() -> None:
    from providers.juspay_astro import parse_juspay_careers_html

    html = """
    <astro-island props='{"jobs":[[0,[{"job_id":[0,"DEV-BE02"],"job_title":[0,"Software Development Engineer Backend"],"job_location":[0,"Bangalore"],"job_description":[0,"Build payment systems."],"department":[0,"Engineering"]},{"job_id":[0,"US-1"],"job_title":[0,"US Role"],"job_location":[0,"New York"],"job_description":[0,"US only."]}]]]}'>
    </astro-island>
    """
    jobs = parse_juspay_careers_html(
        html,
        {"company": "Juspay", "endpoint": "https://juspay.io/careers", "industry": "Fintech", "india_only": True},
    )
    check("juspay filters india jobs", len(jobs) == 1)
    check("juspay id", jobs[0]["job_id"] == "DEV-BE02")
    check("juspay title", jobs[0]["title"] == "Software Development Engineer Backend")
    check("juspay jd", jobs[0]["raw_jd_text"] == "Build payment systems.")
    check("juspay url", jobs[0]["job_url"] == "https://juspay.io/careers/DEV-BE02")


def test_waaree_markdown_parser_maps_static_roles() -> None:
    from providers.waaree_static import parse_waaree_markdown

    markdown = """
    ##### Manager / Senior manager - Cyber Security

    Chikhli

    Full Time

    IT

    Conduct threat and risk analysis.

    Apply Now

    ##### SAP SD Functional Consultant

    Mumbai

    Full Time

    IT

    Configure SAP SD processes.

    Apply Now
    """
    jobs = parse_waaree_markdown(
        markdown,
        {"company": "Waaree Group", "endpoint": "https://www.waaree.com/careers/", "industry": "Energy"},
    )
    check("waaree role count", len(jobs) == 2)
    check("waaree first title", jobs[0]["title"] == "Manager / Senior manager - Cyber Security")
    check("waaree first location", jobs[0]["location_city"] == "Chikhli")
    check("waaree first jd", jobs[0]["raw_jd_text"] == "Conduct threat and risk analysis.")
    check("waaree stable id", jobs[0]["job_id"].startswith("waaree_group_"))


def main() -> None:
    test_radancy_listing_links_parse()
    test_radancy_job_card_links_parse()
    test_palo_alto_section29_links_parse()
    test_cargill_bare_talentbrew_links_parse()
    test_icims_html_listing_parser_maps_job_cards()
    test_search_jobs_pagination_uses_p_param()
    test_publicis_search_payload_maps_india_docs()
    test_cognizant_xml_parser_filters_india()
    test_apple_search_result_maps_india_job()
    test_tata_elxsi_listing_cards_parse()
    test_tata_elxsi_detail_extracts_jd_and_apply_url()
    test_vector_next_data_parser_maps_jobs_and_body_sections()
    test_deshaw_next_data_parser_maps_public_regular_jobs()
    test_intouchcx_feed_filters_india_and_maps_ids()
    test_intouchcx_legacy_detail_extracts_application_body()
    test_intouchcx_dayforce_next_data_extracts_detail()
    test_google_careers_html_parser_maps_embedded_jobs()
    test_microsoft_pcsx_search_parser_maps_india_positions()
    test_microsoft_detail_parser_maps_full_jd()
    test_hilabs_html_parser_maps_india_jobs()
    test_blackbrix_listing_and_detail_parsers()
    test_ashby_job_board_parser_maps_description_plain()
    test_trakstar_listing_fetches_detail_and_filters_india()
    test_rippling_listing_and_detail_next_data_parse()
    test_rippling_listing_dehydrated_state_parse()
    test_workline_listing_and_detail_parse()
    test_peoplestrong_listing_payload_parse()
    test_ubs_brassring_embedded_results_parse()
    test_bdo_map_links_keep_only_job_details()
    test_cornerstone_search_and_detail_payloads_map_india_jobs()
    test_virtusa_map_and_markdown_parsers_create_stable_jobs()
    test_dejobs_rss_parser_maps_india_items()
    test_talent500_parser_fetches_detail_and_filters_india()
    test_oracle_nested_scraper_paginates_offsets()
    test_sap_jobs2web_accepts_bare_in_country_token()
    test_ripplehire_jobvolist_and_detail_payload_map_to_job()
    test_zoho_recruit_builds_company_specific_apply_url()
    test_juspay_astro_parser_maps_embedded_india_jobs()
    test_waaree_markdown_parser_maps_static_roles()
    print("All direct endpoint provider tests passed.")


if __name__ == "__main__":
    main()
