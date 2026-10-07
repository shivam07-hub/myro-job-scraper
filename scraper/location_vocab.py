"""Place vocabulary for location fields: countries, Indian states and cities.

Two rules live here (CEO decision record 2026-10-04):

- A country or a state is never a city. A posting that names only "India" or
  only "Maharashtra" keeps its country and states and leaves the city NULL.
- Myro is India-only. A posting is dropped only when it is positively outside
  India (``foreign_signal``); an unrecognised place is kept.

``india_cities.json`` is the one city -> state list. ``python location_vocab.py
--write-seed`` copies it, with the country and state names below, into
``sql/seed_location_vocab.sql`` so Myro reads the same list from
``public.location_vocab``.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_SPACE_RE = re.compile(r"\s+")
_CITIES_PATH = Path(__file__).with_name("india_cities.json")
SEED_PATH = Path(__file__).with_name("sql") / "seed_location_vocab.sql"

# Sovereign states plus the territories and short forms job boards actually
# print. Lowercase; matched against a whole token, never a substring.
# Georgia is left out: on a job board it is almost always the US state.
_COUNTRY_NAMES = frozenset({
    "afghanistan", "albania", "algeria", "andorra", "angola", "antigua and barbuda",
    "argentina", "armenia", "australia", "austria", "azerbaijan", "bahamas", "bahrain",
    "bangladesh", "barbados", "belarus", "belgium", "belize", "benin", "bhutan",
    "bolivia", "bosnia and herzegovina", "botswana", "brazil", "brunei", "bulgaria",
    "burkina faso", "burundi", "cabo verde", "cambodia", "cameroon", "canada",
    "central african republic", "chad", "chile", "china", "colombia", "comoros",
    "congo", "costa rica", "cote d'ivoire", "côte d'ivoire", "ivory coast", "croatia",
    "cuba", "cyprus", "czechia", "czech republic", "democratic republic of the congo",
    "denmark", "djibouti", "dominica", "dominican republic", "ecuador", "egypt",
    "el salvador", "equatorial guinea", "eritrea", "estonia", "eswatini", "ethiopia",
    "fiji", "finland", "france", "gabon", "gambia", "germany", "ghana",
    "greece", "grenada", "guatemala", "guinea", "guinea-bissau", "guyana", "haiti",
    "honduras", "hong kong", "hungary", "iceland", "india", "indonesia", "iran", "iraq",
    "ireland", "israel", "italy", "jamaica", "japan", "jordan", "kazakhstan", "kenya",
    "kiribati", "korea", "south korea", "republic of korea", "north korea", "kosovo",
    "kuwait", "kyrgyzstan", "laos", "latvia", "lebanon", "lesotho", "liberia", "libya",
    "liechtenstein", "lithuania", "luxembourg", "macau", "macao", "madagascar", "malawi",
    "malaysia", "maldives", "mali", "malta", "marshall islands", "mauritania",
    "mauritius", "mexico", "micronesia", "moldova", "monaco", "mongolia", "montenegro",
    "morocco", "mozambique", "myanmar", "namibia", "nauru", "nepal", "netherlands",
    "the netherlands", "new zealand", "nicaragua", "niger", "nigeria", "north macedonia",
    "norway", "oman", "pakistan", "palau", "palestine", "panama", "papua new guinea",
    "paraguay", "peru", "philippines", "poland", "portugal", "puerto rico", "qatar",
    "romania", "russia", "russian federation", "rwanda", "saint kitts and nevis",
    "saint lucia", "saint vincent and the grenadines", "samoa", "san marino",
    "sao tome and principe", "saudi arabia", "ksa", "senegal", "serbia", "seychelles",
    "sierra leone", "singapore", "slovakia", "slovenia", "solomon islands", "somalia",
    "south africa", "south sudan", "spain", "sri lanka", "sudan", "suriname", "sweden",
    "switzerland", "syria", "taiwan", "tajikistan", "tanzania", "thailand",
    "timor-leste", "togo", "tonga", "trinidad and tobago", "tunisia", "turkey",
    "türkiye", "turkiye", "turkmenistan", "tuvalu", "uganda", "ukraine",
    "united arab emirates", "uae", "united kingdom", "uk", "u.k.", "great britain",
    "england", "scotland", "wales", "northern ireland", "united states",
    "united states of america", "usa", "u.s.a.", "us", "u.s.", "uruguay", "uzbekistan",
    "vanuatu", "vatican city", "venezuela", "vietnam", "viet nam", "yemen", "zambia",
    "zimbabwe",
})

# Names that are a state and never a city -> canonical state. Territories that
# are also cities (Chandigarh, Puducherry, Delhi) are cities in india_cities.json.
_INDIA_STATES = {
    "andhra pradesh": "Andhra Pradesh", "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam", "bihar": "Bihar", "chhattisgarh": "Chhattisgarh", "goa": "Goa",
    "gujarat": "Gujarat", "haryana": "Haryana", "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand", "karnataka": "Karnataka", "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh", "maharashtra": "Maharashtra", "manipur": "Manipur",
    "meghalaya": "Meghalaya", "mizoram": "Mizoram", "nagaland": "Nagaland",
    "odisha": "Odisha", "orissa": "Odisha", "punjab": "Punjab", "rajasthan": "Rajasthan",
    "sikkim": "Sikkim", "tamil nadu": "Tamil Nadu", "telangana": "Telangana",
    "tripura": "Tripura", "uttar pradesh": "Uttar Pradesh", "uttarakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand", "west bengal": "West Bengal",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "jammu and kashmir": "Jammu and Kashmir", "jammu & kashmir": "Jammu and Kashmir",
    "ladakh": "Ladakh", "lakshadweep": "Lakshadweep",
}
_STATE_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in sorted(_INDIA_STATES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Positive "outside India" signals besides country names. Whole tokens only.
_US_STATES = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
})
_CANADA_PROVINCES = frozenset({
    "ontario", "quebec", "british columbia", "alberta", "manitoba", "saskatchewan",
    "nova scotia", "new brunswick", "newfoundland and labrador", "prince edward island",
})
_FOREIGN_CITIES = frozenset({
    "london", "manchester", "edinburgh", "sheffield", "birmingham", "glasgow", "leeds",
    "new york", "new york city", "san francisco", "seattle", "austin", "boston", "chicago",
    "atlanta", "dallas", "houston", "los angeles", "san jose", "denver", "miami",
    "toronto", "mississauga", "markham", "vancouver", "montreal", "ottawa", "calgary",
    "mexico city", "sao paulo", "são paulo", "buenos aires", "bogota", "santiago",
    "paris", "berlin", "munich", "frankfurt", "hamburg", "amsterdam", "rotterdam",
    "dublin", "zurich", "geneva", "brussels", "madrid", "barcelona", "lisbon", "milan",
    "rome", "vienna", "prague", "warsaw", "krakow", "kraków", "wroclaw", "budapest",
    "bucharest", "sofia", "athens", "stockholm", "oslo", "copenhagen", "helsinki",
    "tokyo", "osaka", "seoul", "shanghai", "beijing", "shenzhen", "taipei", "manila",
    "kuala lumpur", "jakarta", "bangkok", "ho chi minh city", "hanoi", "sydney",
    "melbourne", "brisbane", "auckland", "dubai", "abu dhabi", "riyadh", "doha",
    "tel aviv", "cairo", "johannesburg", "cape town", "nairobi", "lagos", "colombo",
    "dhaka", "kathmandu", "karachi", "lahore", "islamabad",
})


def _key(text: str | None) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip().strip(".,;|-").strip()).lower()


@lru_cache(maxsize=1)
def _cities() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]], dict[str, tuple[str, ...]]]:
    """(canonical city key -> (city, state), alias key -> (city, state), metro -> members)."""
    data = json.loads(_CITIES_PATH.read_text(encoding="utf-8"))
    cities: dict[str, tuple[str, str]] = {}
    for state, names in data["cities"].items():
        for name in names:
            cities[_key(name)] = (name, state)
    aliases = {_key(alias): cities[_key(target)] for alias, target in data["aliases"].items()}
    metros = {_key(name): tuple(members) for name, members in data["metro_regions"].items()}
    return cities, aliases, metros


def is_country_name(text: str | None) -> bool:
    """True when the whole string is a country ("India", "United States", "UK")."""
    key = _key(text)
    return bool(key) and key in _COUNTRY_NAMES


def india_state(text: str | None) -> str | None:
    """The canonical state when the whole string is a state that is never a city."""
    return _INDIA_STATES.get(_key(text))


def is_india_state(text: str | None) -> bool:
    return india_state(text) is not None


def india_city(text: str | None) -> tuple[str, str] | None:
    """(canonical city, state) for a known Indian city or alias, else None."""
    key = _key(text)
    if not key:
        return None
    cities, aliases, _ = _cities()
    return cities.get(key) or aliases.get(key)


def states_in(text: str | None) -> list[str]:
    """Indian states named anywhere in a location string, in order, deduped.

    "Karnataka - India Maharashtra - India" -> ["Karnataka", "Maharashtra"].
    """
    out: list[str] = []
    for match in _STATE_RE.finditer(str(text or "")):
        state = _INDIA_STATES[match.group(1).lower()]
        if state not in out:
            out.append(state)
    return out


def _tokens(text: str) -> list[str]:
    pieces = [p for part in re.split(r"[;,|/()]", text) for p in re.split(r"\s+-\s+", part)]
    out: list[str] = []
    for piece in pieces:
        piece = _key(piece)
        if not piece:
            continue
        out.append(piece)
        # "Toronto-Ontario-Ca" is one token to the comma splitter.
        if "-" in piece:
            out.extend(_key(p) for p in piece.split("-") if _key(p))
    return out


def foreign_signal(text: str | None) -> bool:
    """True when the string names a place outside India: a non-India country,
    a US state, a Canadian province or a well-known foreign city."""
    for token in _tokens(str(text or "")):
        # "Mississauga On" / "Austin Tx": a trailing two-letter region code.
        stem = re.sub(r"\s+[a-z]{2}$", "", token)
        for candidate in {token, stem}:
            if candidate in _COUNTRY_NAMES and candidate != "india":
                return True
            if candidate in _US_STATES or candidate in _CANADA_PROVINCES or candidate in _FOREIGN_CITIES:
                return True
    return False


def metro_members(text: str | None) -> tuple[str, ...]:
    """Cities a metro region stands for ("Delhi NCR" -> Delhi NCR, Gurugram, Noida)."""
    return _cities()[2].get(_key(text), ())


def location_fields(location: str | None) -> dict[str, object]:
    """Adapter output for one location string.

    A bare country stays the country and leaves the city NULL; a bare state also
    records the state. Anything else is passed through as the city-bearing
    location for the importer to parse.
    """
    text = _SPACE_RE.sub(" ", str(location or "")).strip()
    if not text:
        return {"location_city": None, "location_country": None}
    if is_country_name(text):
        return {"location_city": None, "location_country": text}
    state = india_state(text)
    if state:
        return {"location_city": None, "location_country": "India", "location_states": [state]}
    return {"location_city": text, "location_country": None}


# ── Myro copy: public.location_vocab ─────────────────────────────────────────


def _sql(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def seed_rows() -> list[tuple[str, str, str, str | None]]:
    """(kind, key, canonical, state) rows, sorted, for public.location_vocab."""
    cities, aliases, metros = _cities()
    rows: set[tuple[str, str, str, str | None]] = set()
    rows.update(("country", name, name, None) for name in _COUNTRY_NAMES)
    rows.update(("state", key, state, state) for key, state in _INDIA_STATES.items())
    rows.update(("city", key, city, state) for key, (city, state) in cities.items())
    rows.update(("alias", key, city, state) for key, (city, state) in aliases.items())
    for metro, members in metros.items():
        rows.update(("metro", metro, member, cities[_key(member)][1]) for member in members)
    return sorted(rows, key=lambda row: (row[0], row[1], row[2]))


def seed_sql() -> str:
    values = ",\n".join(
        f"  ({_sql(kind)}, {_sql(key)}, {_sql(canonical)}, {_sql(state)})"
        for kind, key, canonical, state in seed_rows()
    )
    return (
        "-- GENERATED by `python location_vocab.py --write-seed` from\n"
        "-- scraper/india_cities.json and scraper/location_vocab.py. Do not edit by hand.\n"
        "-- Re-runnable: replaces the whole vocabulary in one transaction.\n"
        "BEGIN;\n"
        "DELETE FROM public.location_vocab;\n"
        "INSERT INTO public.location_vocab (kind, key, canonical, state) VALUES\n"
        f"{values};\n"
        "COMMIT;\n"
    )


if __name__ == "__main__":
    import sys

    if sys.argv[1:] != ["--write-seed"]:
        raise SystemExit("usage: python location_vocab.py --write-seed")
    SEED_PATH.write_text(seed_sql(), encoding="utf-8")
    print(f"wrote {SEED_PATH} ({len(seed_rows())} rows)")
