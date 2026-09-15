"""Deterministic source-owned Career Band normalization for scraped jobs."""
from __future__ import annotations

import re
from typing import Any


_ROLE_DOMAIN_BANDS = {
    "software engineering": "engineering_data",
    "data & analytics": "engineering_data",
    "it & infrastructure": "engineering_data",
    "manufacturing": "engineering_data",
    "finance": "business_product_operations",
    "strategy & consulting": "business_product_operations",
    "sales & marketing": "business_product_operations",
    "operations": "business_product_operations",
    "product management": "business_product_operations",
    "risk & compliance": "business_product_operations",
    "general management": "business_product_operations",
    "supply chain": "business_product_operations",
    "research & science": "research_people_public_impact",
    "hr & people": "research_people_public_impact",
    "legal & compliance": "research_people_public_impact",
}

VALID_CAREER_BANDS = frozenset(_ROLE_DOMAIN_BANDS.values()) | {"design_creative"}

_DESIGN_TITLE = re.compile(
    r"\b(?:ux|ui|product|graphic|visual|brand|motion|content|creative)\s+"
    r"(?:designer|design|writer|artist|illustrator)\b|"
    r"\b(?:designer|copywriter|illustrator|art director)\b|\b(?:ux|ui)\b",
    re.IGNORECASE,
)
_DESIGN_TECH_TITLE = re.compile(
    r"\b(?:ux|ui|user interface|front[ -]?end|web)\b.*"
    r"\b(?:engineer|developer|architect)\b|"
    r"\b(?:engineer|developer|architect)\b.*"
    r"\b(?:ux|ui|user interface|front[ -]?end|web)\b",
    re.IGNORECASE,
)
_TECHNICAL_SCIENTIST = re.compile(
    # "scientist" alone is a research occupation, but these compounds are
    # engineering roles and must be claimed before _PUBLIC_IMPACT_OCCUPATION
    # sees the bare word. The band guide puts "data, AI" in engineering_data,
    # so a Data Scientist banding as research/people/public impact was wrong —
    # it also hid them from the technical keep-set in scrape_select.
    # "Research Scientist" is deliberately absent: in pharma and clinical work
    # that is the research band, and the bare word belongs to public impact.
    r"\b(?:data|machine learning|\bml\b|ai|applied|computer|decision)\s+"
    r"scientist\b|\bresearch engineer\b",
    re.IGNORECASE,
)
_PUBLIC_IMPACT_OCCUPATION = re.compile(
    r"\b(?:counsel|lawyer|attorney|paralegal|patent|recruiter|recruiting|"
    r"human resources|\bhr\b|people partner|talent acquisition|scientist|"
    r"clinical|medical|physician|pharmacist|pharmacovigilance|regulatory affairs|"
    r"laborator(?:y|ies)|social impact|public affairs|government relations|"
    r"employee relations|industrial relations)\b",
    re.IGNORECASE,
)
_BUSINESS_TECH_HYBRID = re.compile(
    r"\b(?:sales engineer|solutions? consultant|technical account manager|"
    r"customer success|commercialization)\b",
    re.IGNORECASE,
)
_TECHNICAL_OCCUPATION = re.compile(
    r"\b(?:software|data|machine learning|ai|devops|sre|cloud|cyber|security|"
    r"qa|quality assurance|platform|backend|front[ -]?end|full[ -]?stack|"
    r"engineering|engineer|developer|programmer|architect|infrastructure|"
    r"manufacturing|embedded|systems?|database|network|automation|analytics|technician|"
    r"technology|technical|sap|erp|sde|service desk|application|infra|"
    r"integration|integ|tech|test(?:ing)?|sdet|engr|mechanical|production|"
    r"quality control|quality specialist|continuous improvement|r\s*&\s*d|"
    r"kafka|snowflake|hadoop|"
    r"informatica|geospatial|\bit\b|administrator(?:\s*-\s*|\s+)l[0-4])\b",
    re.IGNORECASE,
)
_BUSINESS_TITLE = re.compile(
    r"\b(?:product manager|business development|marketing|marketer|sales|finance|"
    r"financial|f\s*&\s*a|fp\s*&\s*a|accounting|accountant|audit|tax|controller|"
    r"accounts?\s+(?:receivable|payable)|receivables|payables|"
    r"banker|banking|branch|teller|relationship (?:manager|officer)|customer service|"
    r"customer support|administrative|"
    r"account manager|underwrit(?:er|ing)|insurance|claims?|treasury|credit|"
    r"consultant|consulting|strategy|operations|business analyst|supply chain|"
    r"procurement|revenue|account executive|partnerships?|growth|category|"
    r"project manager|project leader|program manager|scrum master|commercial|planning|planner|"
    r"advisory|customer care|customer contact|client account management|"
    r"asset\s*&\s*wealth|fund servicing|product owner|product management|buyer|"
    r"buying|purchasing|collections?|lending|"
    r"loan|working capital|valuations?|controllership|middle office|"
    r"program\s*&\s*project management|executive assistant|grc|actuary|"
    r"actuarial|trade services|engagement manager|proposal|financial reporting|"
    r"business service support|reinsurance|treaty|communications?|engagement|"
    r"t\s*&\s*e|warehouse|order handling|"
    r"dispatch|logistics|travel\s*(?:&|and)\s*expenses?|corporate card|customs|"
    r"transportation|market development|procurment|"
    # Generic business-function words the rules simply lacked, taken from the
    # 2026-08-08 withheld set. Deliberately no employer-private vocabulary —
    # a title like "CBG:Circle Head" resolves on "circle head", not on "CBG".
    r"acquisition manager|campaign|channel (?:manager|support|partner)|"
    r"(?:circle|geography|centre|center|state|regional|zonal|cluster) head|"
    r"portfolio manager|investment (?:specialist|counsell?or|advisor|advisory)|"
    r"due diligence|managed services|wealth|private banking|deal value|"
    # Second pass over the 2026-08-08 withheld set. Same rule as above: generic
    # function words only. "risk" sits after _TECHNICAL_OCCUPATION, so a Risk
    # Engineer still bands as engineering — only the unqualified risk roles
    # (operational, market, climate, credit) land here.
    r"risk|client servic\w*|vendor manage\w*|sourcing|assurance|"
    r"know your customer|\bkyc\b|business (?:expert|pro|management|support|control))\b",
    re.IGNORECASE,
)
_PUBLIC_IMPACT_TITLE = re.compile(
    r"\b(?:research|policy|people|talent|legal|compliance|community|education|"
    r"learning|training|programme? officer|hro|payroll|benefits|contracts?|"
    r"employee vetting|background checks?|health admin services|hse|"
    r"health,?\s+safety(?:,?\s+and)?\s+environment|sustainability)\b",
    re.IGNORECASE,
)


def normalize_job_career_band(job: dict[str, Any]) -> str:
    """Map source metadata/title to one of Myro's four role families.

    Explicit title signals take precedence over a broader role domain so that a
    Product Designer stays in Design & Creative rather than Product Management.
    Unknown evidence stays blank. Employer industry is deliberately excluded:
    it describes the company, not the function of an individual role.
    """
    title = str(job.get("job_title") or job.get("title") or "")
    for pattern, band in (
        (_DESIGN_TECH_TITLE, "engineering_data"),
        (_DESIGN_TITLE, "design_creative"),
        (_TECHNICAL_SCIENTIST, "engineering_data"),
        (_PUBLIC_IMPACT_OCCUPATION, "research_people_public_impact"),
        (_BUSINESS_TECH_HYBRID, "business_product_operations"),
        (_TECHNICAL_OCCUPATION, "engineering_data"),
        (_BUSINESS_TITLE, "business_product_operations"),
        (_PUBLIC_IMPACT_TITLE, "research_people_public_impact"),
    ):
        if pattern.search(title):
            return band
    role_domain = job.get("role_domain") or ""
    return _ROLE_DOMAIN_BANDS.get(str(role_domain).strip().casefold(), "")
