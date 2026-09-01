from __future__ import annotations

from portal_reader import parse_portals


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


def _portal(company: str) -> dict:
    matches = [p for p in parse_portals() if p.get("company") == company]
    if not matches:
        raise AssertionError(f"portal missing: {company}")
    return matches[0]


def test_direct_endpoint_routes() -> None:
    expected = {
        "Apple": "apple_jobs",
        "Cognizant": "cognizant_xml",
        "Google": "google_careers",
        "STMicroelectronics": "eightfold",
        "American Express": "oracle",
        "Citibank": "talentbrew",
        "AstraZeneca": "talentbrew",
        "Eli Lilly": "phenom_ssr",
        "Cisco": "phenom_ssr",
        "BCG": "phenom_ssr",
        "LTIMindtree": "sap_jobs2web_html",
        "GMR Group": "sap_jobs2web_html",
        "HP (HPE)": "phenom_ssr",
        "HiLabs": "hilabs_careers",
        "Tata Elxsi": "tata_elxsi",
        "Vector Consulting Group": "vector_consulting",
        "DE Shaw": "deshaw_india",
        "IntouchCX": "intouchcx",
        "Microsoft": "microsoft_careers",
        "Black Brix": "blackbrix_jobs",
        "ARM Holdings": "talentbrew",
        "Godrej Consumer Products": "phenom_ssr",
        "Philip Morris International": "phenom_ssr",
        "Publicis Sapient": "publicis_sapient",
        "InMobi": "greenhouse",
        "CRISIL": "zwayam",
        "NVIDIA": "pcsx",
        "Micron Technology": "pcsx",
        "Qualcomm": "pcsx",
        "PayPal": "pcsx",
        "Snowflake": "ashby",
        "Confluent": "ashby",
        "Rippling": "rippling",
        "Nutanix": "dejobs_rss",
        "Palo Alto Networks": "talentbrew",
        "Anthropic": "greenhouse",
        "Postman": "greenhouse",
        "Zuora": "greenhouse",
        "Cloudflare": "greenhouse",
        "Point72": "greenhouse",
        "Figma": "greenhouse",
        "GitLab": "greenhouse",
        "Druva": "greenhouse",
        "Sumo Logic": "greenhouse",
        "Netskope": "greenhouse",
        "HackerRank": "greenhouse",
        "Observe.ai": "greenhouse",
        "ClickHouse": "greenhouse",
        "DAT Freight & Analytics": "greenhouse",
        "Energy Exemplar": "greenhouse",
        "AlphaSense India": "greenhouse",
        "Bluevine India": "greenhouse",
        "Kaseya": "greenhouse",
        "NICE": "greenhouse",
        "Ivalua": "greenhouse",
        "Abacus Insights": "greenhouse",
        "JAGGAER": "icims_html",
        "UiPath": "ashby",
        "Airwallex": "ashby",
        "Notion": "ashby",
        "Atlan": "ashby",
        "Cartesia": "ashby",
        "Fermi AI": "ashby",
        "Flagright": "ashby",
        "Skylo Technologies": "ashby",
        "Cognition": "ashby",
        "Costco Wholesale": "talent500",
        "Workday": "workday",
        "Sprinklr": "workday",
        "Automation Anywhere": "workday",
        "Vanguard Group": "workday",
        "KLA Corporation": "workday",
        "Carrier Global": "workday",
        "ThoughtSpot": "workday",
        "Cohesity": "workday",
        "BrowserStack": "workday",
        "Western Digital": "smartrecruiters",
        "Genpact": "workday",
        "Boeing": "talentbrew",
        "Infineon Technologies": "pcsx",
        "Lam Research": "pcsx",
        "Teradyne": "sap_jobs2web_html",
        "McDonald's GCC": "sap_jobs2web_html",
        "Vertiv": "oracle",
        "Icertis": "oracle",
        "Cargill": "talentbrew",
        "Mindtickle": "lever",
        "Zeta": "lever",
        "JumpCloud": "lever",
        "Zimperium": "lever",
        "Hevo Data": "lever",
        "Acceldata": "lever",
        "Onehouse": "lever",
        "Asian Paints": "sap_jobs2web_html",
        "Bajaj Auto": "sap_jobs2web_html",
        "Tata Consumer Products": "sap_jobs2web_html",
        "Sun Pharma": "sap_jobs2web_html",
        "Syngene": "sap_jobs2web_html",
        "AB InBev": "workday",
        "Mondelez": "workday",
        "Kraft Heinz": "workday",
        "Axis Bank": "ripplehire",
        "Tata Steel": "ripplehire",
        "Kotak Mahindra Bank": "oracle",
        "NPCI": "zoho_recruit",
        "Juspay": "juspay_astro",
        "Waaree Group": "waaree_static",
        "Whatfix": "trakstar",
        "Sanas": "rippling",
        "Premji Invest": "zoho_recruit",
        "SBI Mutual Fund": "workline",
        "Lodha Group": "peoplestrong",
        "UBS": "ubs_brassring",
        "BDO India": "bdo_firecrawl",
        "Simon-Kucher & Partners": "cornerstone",
        "Virtusa": "virtusa_firecrawl",
        "Kearney": "yello",
        "Celonis": "greenhouse",
        "Glean": "greenhouse",
        "Boomi": "greenhouse",
        "Hightouch": "greenhouse",
        "Hootsuite": "greenhouse",
        "Deepgram": "ashby",
        "Zapier": "ashby",
        "H&M": "smartrecruiters",
        "Tekion": "ashby",
        "TVS Next": "keka",
        "Coforge": "zwayam",
        "Amdocs": "pcsx",
        "S&P Global": "jibe",
        "Elevation Capital": "workable",
        "Yubi": "yubi_careers",
    }
    for company, ats in expected.items():
        portal = _portal(company)
        check(f"{company} ats", portal["ats"] == ats)
        check(f"{company} no firecrawl", not portal.get("js_required"))


def main() -> None:
    test_direct_endpoint_routes()
    print("All direct endpoint routing tests passed.")


if __name__ == "__main__":
    main()
