from __future__ import annotations

from schema import Portal

import logging

from providers.base import FALLBACK_FIRECRAWL_EXTRACT, Provider, ProviderResult, ScrapeReason
from providers.eightfold import EightfoldProvider
from providers.firecrawl_js import FirecrawlJSProvider
from providers.darwinbox import DarwinboxProvider
from providers.google_careers import GoogleCareersProvider
from providers.mynexthire import MyNextHireProvider
from providers.icims_custom import IcimsCustomProvider
from providers.icims_html import IcimsHTMLProvider
from providers.juspay_astro import JuspayAstroProvider
from providers.goldman_higher import GoldmanHigherProvider
from providers.intouchcx import IntouchCXProvider
from providers.microsoft_careers import MicrosoftCareersProvider
from providers.mckinsey import McKinseyProvider
from providers.aditya_birla import AdityaBirlaProvider
from providers.apple_jobs import AppleJobsProvider
from providers.ashby import AshbyProvider
from providers.blackbrix_jobs import BlackBrixJobsProvider
from providers.cognizant_xml import CognizantXMLProvider
from providers.cornerstone import CornerstoneProvider
from providers.dejobs_rss import DejobsRSSProvider
from providers.deshaw_india import DEShawIndiaProvider
from providers.pcsx import PCSXProvider
from providers.taleo import TaleoProvider
from providers.talentbrew import TalentBrewProvider
from providers.talent500 import Talent500Provider
from providers.trakstar import TrakstarProvider
from providers.phenom_ssr import PhenomSSRProvider
from providers.siemens_externaljobs import SiemensExternalJobsProvider
from providers.deloitte_usi import DeloitteUSIProvider
from providers.yello import YelloProvider
from providers.sap_jobs2web_html import SAPJobs2WebHTMLProvider
from providers.tata_elxsi import TataElxsiProvider
from providers.vector_consulting import VectorConsultingProvider
from providers.waaree_static import WaareeStaticProvider
from providers.pepsico_jobs_api import PepsiCoJobsAPIProvider
from providers.publicis_sapient import PublicisSapientProvider
from providers.rippling import RipplingProvider
from providers.skima_careers import SkimaCareersProvider
from providers.hilabs_careers import HiLabsCareersProvider
from providers.michelin_astro import MichelinAstroProvider
from providers.pinpoint import PinpointProvider
from providers.spire2grow import Spire2GrowProvider
from providers.zwayam import ZwayamProvider
from providers.ripplehire import RippleHireProvider
from providers.generic_json import GenericJSONProvider
from providers.greenhouse import GreenhouseProvider
from providers.lever import LeverProvider
from providers.phenom import PhenomProvider
from providers.smartrecruiters import SmartRecruitersProvider
from providers.workday import WorkdayProvider
from providers.zoho_recruit import ZohoRecruitProvider
from providers.msci_algolia import MsciAlgoliaProvider
from providers.meta_graphql import MetaGraphQLProvider
from providers.peoplestrong import PeopleStrongProvider
from providers.ubs_brassring import UBSBrassRingProvider
from providers.virtusa_firecrawl import VirtusaFirecrawlProvider
from providers.workline import WorklineProvider
from providers.bdo_firecrawl import BDOFirecrawlProvider
from providers.keka import KekaProvider
from providers.jibe import JibeProvider
from providers.workable import WorkableProvider
from providers.yubi_careers import YubiCareersProvider

_FIRECRAWL_PROVIDER = FirecrawlJSProvider()
_GENERIC_PROVIDER = GenericJSONProvider()

_ATS_PROVIDERS: dict[str, Provider] = {
    "workday": WorkdayProvider(),
    "smartrecruiters": SmartRecruitersProvider(),
    "greenhouse": GreenhouseProvider(),
    "lever": LeverProvider(),
    "phenom_api": PhenomProvider(),
    "eightfold": EightfoldProvider(),
    "google_careers": GoogleCareersProvider(),
    "icims_custom": IcimsCustomProvider(),
    "icims_html": IcimsHTMLProvider(),
    "juspay_astro": JuspayAstroProvider(),
    "goldman_higher": GoldmanHigherProvider(),
    "intouchcx": IntouchCXProvider(),
    "microsoft_careers": MicrosoftCareersProvider(),
    "darwinbox": DarwinboxProvider(),
    "mynexthire": MyNextHireProvider(),
    "mckinsey": McKinseyProvider(),
    "aditya_birla": AdityaBirlaProvider(),
    "apple_jobs": AppleJobsProvider(),
    "ashby": AshbyProvider(),
    "blackbrix_jobs": BlackBrixJobsProvider(),
    "cognizant_xml": CognizantXMLProvider(),
    "cornerstone": CornerstoneProvider(),
    "deshaw_india": DEShawIndiaProvider(),
    "dejobs_rss": DejobsRSSProvider(),
    "pinpoint": PinpointProvider(),
    "pcsx": PCSXProvider(),
    "taleo": TaleoProvider(),
    "talentbrew": TalentBrewProvider(),
    "talent500": Talent500Provider(),
    "trakstar": TrakstarProvider(),
    "phenom_ssr": PhenomSSRProvider(),
    "siemens_externaljobs": SiemensExternalJobsProvider(),
    "deloitte_usi": DeloitteUSIProvider(),
    "yello": YelloProvider(),
    "sap_jobs2web_html": SAPJobs2WebHTMLProvider(),
    "tata_elxsi": TataElxsiProvider(),
    "vector_consulting": VectorConsultingProvider(),
    "waaree_static": WaareeStaticProvider(),
    "pepsico_jobs_api": PepsiCoJobsAPIProvider(),
    "publicis_sapient": PublicisSapientProvider(),
    "rippling": RipplingProvider(),
    "skima_careers": SkimaCareersProvider(),
    "hilabs_careers": HiLabsCareersProvider(),
    "michelin_astro": MichelinAstroProvider(),
    "spire2grow": Spire2GrowProvider(),
    "zwayam": ZwayamProvider(),
    "ripplehire": RippleHireProvider(),
    "zoho_recruit": ZohoRecruitProvider(),
    "msci_algolia": MsciAlgoliaProvider(),
    "meta_graphql": MetaGraphQLProvider(),
    "peoplestrong": PeopleStrongProvider(),
    "ubs_brassring": UBSBrassRingProvider(),
    "virtusa_firecrawl": VirtusaFirecrawlProvider(),
    "workline": WorklineProvider(),
    "bdo_firecrawl": BDOFirecrawlProvider(),
    "keka": KekaProvider(),
    "jibe": JibeProvider(),
    "workable": WorkableProvider(),
    "yubi_careers": YubiCareersProvider(),
}


def _provider_for_portal(portal: Portal) -> Provider:
    if portal.get("js_required"):
        return _FIRECRAWL_PROVIDER
    return _ATS_PROVIDERS.get(portal.get("ats", ""), _GENERIC_PROVIDER)


def _run_firecrawl_result(
    portal: Portal,
    log: logging.Logger,
    *,
    max_jobs: int | None,
    validate_mode: bool,
) -> ProviderResult:
    company = portal["company"]
    result = _FIRECRAWL_PROVIDER.scrape(
        portal,
        max_jobs=max_jobs,
        validate_mode=validate_mode,
    )
    jobs = result.jobs
    if jobs:
        log.info(f"    Firecrawl {'scrape' if validate_mode else 'extract'}: {len(jobs)} entries")
    else:
        log.warning(f"    Firecrawl returned 0 for {company}")
    return result


def _apply_fallback_result(
    result: ProviderResult,
    portal: Portal,
    log: logging.Logger,
    *,
    max_jobs: int | None,
    validate_mode: bool,
) -> ProviderResult:
    if result.fallback_policy != FALLBACK_FIRECRAWL_EXTRACT:
        return result

    fallback_portal = result.fallback_portal or portal
    reason = result.fallback_reason or "fallback_requested"

    if reason in ("workday_api_blocked", "workday_cloudflare_blocked"):
        log.info("    Workday direct API blocked -> falling back to Firecrawl")
    elif reason == "oracle_api_empty_fallback_careers_url":
        log.info("    Oracle REST returned 0 -> falling back to Firecrawl on careers_url")
    else:
        log.info(f"    Provider fallback -> Firecrawl ({reason})")

    return _run_firecrawl_result(
        fallback_portal,
        log,
        max_jobs=max_jobs,
        validate_mode=validate_mode,
    )


def dispatch_scrape_result(
    portal: Portal,
    log: logging.Logger,
    *,
    max_jobs: int | None = None,
    validate_mode: bool = False,
    on_page_complete=None,  # Callable[[list[dict], int], None] | None — Workday/Taleo only
) -> ProviderResult:
    provider = _provider_for_portal(portal)

    # JS-required portals and explicit Firecrawl usage go through Firecrawl provider directly.
    if provider is _FIRECRAWL_PROVIDER:
        return _run_firecrawl_result(
            portal,
            log,
            max_jobs=max_jobs,
            validate_mode=validate_mode,
        )

    # Only Workday and Taleo support page-level callbacks — others ignore the param safely
    supports_callback = isinstance(provider, (WorkdayProvider, TaleoProvider))
    scrape_kwargs: dict = {"max_jobs": max_jobs, "validate_mode": validate_mode}
    if on_page_complete and supports_callback:
        scrape_kwargs["on_page_complete"] = on_page_complete

    result = provider.scrape(portal, **scrape_kwargs)

    # Log typed reason for non-success outcomes (aids debugging without log-string parsing)
    if result.reason not in (ScrapeReason.SUCCESS, ScrapeReason.NO_JOBS, ScrapeReason.FALLBACK):
        log.warning(f"    [{portal['company']}] scrape reason: {result.reason.value}")

    return _apply_fallback_result(
        result,
        portal,
        log,
        max_jobs=max_jobs,
        validate_mode=validate_mode,
    )


def dispatch_scrape(
    portal: Portal,
    log: logging.Logger,
    *,
    max_jobs: int | None = None,
    validate_mode: bool = False,
    on_page_complete=None,
) -> list[dict]:
    """Backward-compatible jobs-only adapter.

    New pipeline code must use ``dispatch_scrape_result`` so a partial/error
    outcome cannot be collapsed into a seemingly healthy non-empty list.
    """
    return dispatch_scrape_result(
        portal,
        log,
        max_jobs=max_jobs,
        validate_mode=validate_mode,
        on_page_complete=on_page_complete,
    ).jobs


def probe_scrape(
    portal: Portal,
    log: logging.Logger,
    *,
    max_jobs: int | None = None,
    validate_mode: bool = False,
    allow_firecrawl: bool = False,
) -> ProviderResult:
    """Probe one portal without implicit Firecrawl fallback unless allowed.

    Inventory runs need to distinguish "direct route returned zero" from
    "direct route would need Firecrawl". The production dispatch path should keep
    falling back automatically; this probe path is deliberately conservative.
    """
    provider = _provider_for_portal(portal)

    if provider is _FIRECRAWL_PROVIDER and not allow_firecrawl:
        return ProviderResult.fallback(
            policy=FALLBACK_FIRECRAWL_EXTRACT,
            reason="firecrawl_probe_skipped",
            portal=portal,
        )

    result = provider.scrape(
        portal,
        max_jobs=max_jobs,
        validate_mode=validate_mode,
    )

    if result.fallback_policy == FALLBACK_FIRECRAWL_EXTRACT and allow_firecrawl:
        return _apply_fallback_result(
            result,
            portal,
            log,
            max_jobs=max_jobs,
            validate_mode=validate_mode,
        )
    return result
