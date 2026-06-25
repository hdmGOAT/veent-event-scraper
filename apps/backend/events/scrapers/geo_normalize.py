"""Country and region normalization for scraped location strings.

FB and other sources format locations inconsistently:
  - Country codes (PH, SG, US)
  - US state names instead of country (Salt Lake City, Utah)
  - Canadian provinces instead of country (Toronto, Ontario)
  - Alternate spellings / official names (Republic of the Philippines)

Import and call normalize_country(raw) anywhere a raw location string
needs to be mapped to a canonical country name.
"""

# Maps lowercase raw string → canonical country name.
# Checked in order: exact match wins.
_ALIASES: dict[str, str] = {
    # ── Philippines ──────────────────────────────────────────────────────────
    "ph": "Philippines", "phl": "Philippines", "philippines": "Philippines",
    "republic of the philippines": "Philippines", "pilipinas": "Philippines",

    # ── Singapore ────────────────────────────────────────────────────────────
    "sg": "Singapore", "sgp": "Singapore", "singapore": "Singapore",
    "republic of singapore": "Singapore",

    # ── United States — ISO codes + all 50 states + DC ──────────────────────
    "us": "United States", "usa": "United States",
    "u.s.": "United States", "u.s.a.": "United States",
    "united states": "United States", "united states of america": "United States",
    # States (abbreviation + full name)
    "al": "United States", "alabama": "United States",
    "ak": "United States", "alaska": "United States",
    "az": "United States", "arizona": "United States",
    "ar": "United States", "arkansas": "United States",
    "ca": "United States", "california": "United States",
    "co": "United States", "colorado": "United States",
    "ct": "United States", "connecticut": "United States",
    "de": "United States", "delaware": "United States",
    "fl": "United States", "florida": "United States",
    "ga": "United States", "georgia": "United States",
    "hi": "United States", "hawaii": "United States",
    "id": "United States", "idaho": "United States",
    "il": "United States", "illinois": "United States",
    "in": "United States", "indiana": "United States",
    "ia": "United States", "iowa": "United States",
    "ks": "United States", "kansas": "United States",
    "ky": "United States", "kentucky": "United States",
    "la": "United States", "louisiana": "United States",
    "me": "United States", "maine": "United States",
    "md": "United States", "maryland": "United States",
    "ma": "United States", "massachusetts": "United States",
    "mi": "United States", "michigan": "United States",
    "mn": "United States", "minnesota": "United States",
    "ms": "United States", "mississippi": "United States",
    "mo": "United States", "missouri": "United States",
    "mt": "United States", "montana": "United States",
    "ne": "United States", "nebraska": "United States",
    "nv": "United States", "nevada": "United States",
    "nh": "United States", "new hampshire": "United States",
    "nj": "United States", "new jersey": "United States",
    "nm": "United States", "new mexico": "United States",
    "ny": "United States", "new york": "United States",
    "nc": "United States", "north carolina": "United States",
    "nd": "United States", "north dakota": "United States",
    "oh": "United States", "ohio": "United States",
    "ok": "United States", "oklahoma": "United States",
    "or": "United States", "oregon": "United States",
    "pa": "United States", "pennsylvania": "United States",
    "ri": "United States", "rhode island": "United States",
    "sc": "United States", "south carolina": "United States",
    "sd": "United States", "south dakota": "United States",
    "tn": "United States", "tennessee": "United States",
    "tx": "United States", "texas": "United States",
    "ut": "United States", "utah": "United States",
    "vt": "United States", "vermont": "United States",
    "va": "United States", "virginia": "United States",
    "wa": "United States", "washington": "United States",
    "wv": "United States", "west virginia": "United States",
    "wi": "United States", "wisconsin": "United States",
    "wy": "United States", "wyoming": "United States",
    "dc": "United States", "district of columbia": "United States",

    # ── Canada — ISO codes + provinces/territories ───────────────────────────
    # "ca" intentionally omitted: conflicts with California (US state) which takes priority.
    "can": "Canada", "canada": "Canada",
    "ab": "Canada", "alberta": "Canada",
    "bc": "Canada", "british columbia": "Canada",
    "mb": "Canada", "manitoba": "Canada",
    "nb": "Canada", "new brunswick": "Canada",
    "nl": "Canada", "newfoundland and labrador": "Canada",
    "ns": "Canada", "nova scotia": "Canada",
    "on": "Canada", "ontario": "Canada",
    # "pe" intentionally omitted: conflicts with Peru ("pe") added below; pe→PEI retained via full name.
    "prince edward island": "Canada",
    "qc": "Canada", "quebec": "Canada",
    # "sk" intentionally omitted: conflicts with Slovakia ("sk") added below; retained via full name.
    "saskatchewan": "Canada",
    "nt": "Canada", "northwest territories": "Canada",  # takes priority over "nt" → Australia (Northern Territory)
    "nu": "Canada", "nunavut": "Canada",
    "yt": "Canada", "yukon": "Canada",

    # ── United Kingdom ───────────────────────────────────────────────────────
    "uk": "United Kingdom", "gb": "United Kingdom", "gbr": "United Kingdom",
    "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom",
    "northern ireland": "United Kingdom", "united kingdom": "United Kingdom",

    # ── Australia ────────────────────────────────────────────────────────────
    "au": "Australia", "aus": "Australia", "australia": "Australia",
    "nsw": "Australia", "new south wales": "Australia",
    "vic": "Australia", "victoria": "Australia",
    "qld": "Australia", "queensland": "Australia",
    "sa": "Australia", "south australia": "Australia",
    # "wa" omitted: conflicts with Washington (US state) which takes priority.
    "western australia": "Australia",
    "tas": "Australia", "tasmania": "Australia",
    "act": "Australia", "australian capital territory": "Australia",
    # "nt" omitted: "nt" → Canada (Northwest Territories) takes priority.
    "northern territory": "Australia",

    # ── India ─────────────────────────────────────────────────────────────────
    # "in" omitted: conflicts with Indiana (US state) which takes priority.
    "ind": "India", "india": "India",

    # ── Indonesia ─────────────────────────────────────────────────────────────
    "idn": "Indonesia", "indonesia": "Indonesia",

    # ── Malaysia ──────────────────────────────────────────────────────────────
    "my": "Malaysia", "mys": "Malaysia", "malaysia": "Malaysia",

    # ── Thailand ──────────────────────────────────────────────────────────────
    "th": "Thailand", "tha": "Thailand", "thailand": "Thailand",

    # ── Vietnam ───────────────────────────────────────────────────────────────
    "vn": "Vietnam", "vnm": "Vietnam", "vietnam": "Vietnam",
    "viet nam": "Vietnam",

    # ── Japan ─────────────────────────────────────────────────────────────────
    "jp": "Japan", "jpn": "Japan", "japan": "Japan",

    # ── South Korea ───────────────────────────────────────────────────────────
    "kr": "South Korea", "kor": "South Korea",
    "south korea": "South Korea", "korea": "South Korea",

    # ── Germany ───────────────────────────────────────────────────────────────
    # "de" omitted: conflicts with Delaware (US state) which takes priority.
    "deu": "Germany", "germany": "Germany",

    # ── France ────────────────────────────────────────────────────────────────
    "fr": "France", "fra": "France", "france": "France",

    # ── New Zealand ───────────────────────────────────────────────────────────
    "nz": "New Zealand", "nzl": "New Zealand", "new zealand": "New Zealand",

    # ── UAE ───────────────────────────────────────────────────────────────────
    "ae": "United Arab Emirates", "are": "United Arab Emirates",
    "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates",

    # ── South Africa ──────────────────────────────────────────────────────────
    "za": "South Africa", "zaf": "South Africa", "south africa": "South Africa",

    # ── Belgium ───────────────────────────────────────────────────────────────
    "be": "Belgium", "bel": "Belgium", "belgium": "Belgium",
    "belgique": "Belgium", "belgië": "Belgium", "belgien": "Belgium",

    # ── Finland ───────────────────────────────────────────────────────────────
    "fi": "Finland", "fin": "Finland", "finland": "Finland",
    "suomi": "Finland",

    # ── Denmark ───────────────────────────────────────────────────────────────
    "dk": "Denmark", "dnk": "Denmark", "denmark": "Denmark",
    "danmark": "Denmark",

    # ── Portugal ──────────────────────────────────────────────────────────────
    "pt": "Portugal", "prt": "Portugal", "portugal": "Portugal",

    # ── Spain ─────────────────────────────────────────────────────────────────
    "es": "Spain", "esp": "Spain", "spain": "Spain",
    "españa": "Spain", "espana": "Spain",

    # ── Italy ─────────────────────────────────────────────────────────────────
    "it": "Italy", "ita": "Italy", "italy": "Italy",
    "italia": "Italy",

    # ── Netherlands ───────────────────────────────────────────────────────────
    "nl": "Netherlands", "nld": "Netherlands", "netherlands": "Netherlands",
    "holland": "Netherlands", "nederland": "Netherlands",

    # ── Sweden ────────────────────────────────────────────────────────────────
    "se": "Sweden", "swe": "Sweden", "sweden": "Sweden",
    "sverige": "Sweden",

    # ── Norway ────────────────────────────────────────────────────────────────
    "no": "Norway", "nor": "Norway", "norway": "Norway",
    "norge": "Norway",

    # ── Switzerland ───────────────────────────────────────────────────────────
    "ch": "Switzerland", "che": "Switzerland", "switzerland": "Switzerland",
    "schweiz": "Switzerland", "suisse": "Switzerland",

    # ── Austria ───────────────────────────────────────────────────────────────
    "at": "Austria", "aut": "Austria", "austria": "Austria",
    "österreich": "Austria", "oesterreich": "Austria",

    # ── Poland ────────────────────────────────────────────────────────────────
    "pl": "Poland", "pol": "Poland", "poland": "Poland",
    "polska": "Poland",

    # ── Brazil ────────────────────────────────────────────────────────────────
    "br": "Brazil", "bra": "Brazil", "brazil": "Brazil",
    "brasil": "Brazil",

    # ── Mexico ────────────────────────────────────────────────────────────────
    "mx": "Mexico", "mex": "Mexico", "mexico": "Mexico",
    "méxico": "Mexico",

    # ── China ─────────────────────────────────────────────────────────────────
    "cn": "China", "chn": "China", "china": "China",
    "prc": "China", "peoples republic of china": "China",

    # ── Hong Kong ─────────────────────────────────────────────────────────────
    "hk": "Hong Kong", "hkg": "Hong Kong", "hong kong": "Hong Kong",

    # ── Taiwan ────────────────────────────────────────────────────────────────
    "tw": "Taiwan", "twn": "Taiwan", "taiwan": "Taiwan",

    # ── Sri Lanka ─────────────────────────────────────────────────────────────
    "lk": "Sri Lanka", "lka": "Sri Lanka", "sri lanka": "Sri Lanka",

    # ── Bangladesh ────────────────────────────────────────────────────────────
    "bd": "Bangladesh", "bgd": "Bangladesh", "bangladesh": "Bangladesh",

    # ── Pakistan ──────────────────────────────────────────────────────────────
    "pk": "Pakistan", "pak": "Pakistan", "pakistan": "Pakistan",

    # ── Nepal ─────────────────────────────────────────────────────────────────
    "np": "Nepal", "npl": "Nepal", "nepal": "Nepal",

    # ── Egypt ─────────────────────────────────────────────────────────────────
    "eg": "Egypt", "egy": "Egypt", "egypt": "Egypt",

    # ── Nigeria ───────────────────────────────────────────────────────────────
    "ng": "Nigeria", "nga": "Nigeria", "nigeria": "Nigeria",

    # ── Kenya ─────────────────────────────────────────────────────────────────
    "ke": "Kenya", "ken": "Kenya", "kenya": "Kenya",

    # ── Ghana ─────────────────────────────────────────────────────────────────
    "gh": "Ghana", "gha": "Ghana", "ghana": "Ghana",

    # ── Ethiopia ──────────────────────────────────────────────────────────────
    "et": "Ethiopia", "eth": "Ethiopia", "ethiopia": "Ethiopia",

    # ── Argentina ─────────────────────────────────────────────────────────────
    # "ar" omitted: conflicts with Arkansas (US state) which takes priority.
    "arg": "Argentina", "argentina": "Argentina",

    # ── Colombia ──────────────────────────────────────────────────────────────
    # "co" omitted: conflicts with Colorado (US state) which takes priority.
    "col": "Colombia", "colombia": "Colombia",

    # ── Peru ──────────────────────────────────────────────────────────────────
    # "pe" omitted: conflicts with Prince Edward Island (Canada) which takes priority.
    "per": "Peru", "peru": "Peru",

    # ── Chile ─────────────────────────────────────────────────────────────────
    "cl": "Chile", "chl": "Chile", "chile": "Chile",

    # ── Turkey ────────────────────────────────────────────────────────────────
    "tr": "Turkey", "tur": "Turkey", "turkey": "Turkey",
    "türkiye": "Turkey", "turkiye": "Turkey",

    # ── Greece ────────────────────────────────────────────────────────────────
    "gr": "Greece", "grc": "Greece", "greece": "Greece",

    # ── Ireland ───────────────────────────────────────────────────────────────
    "ie": "Ireland", "irl": "Ireland", "ireland": "Ireland",
    "republic of ireland": "Ireland", "eire": "Ireland",

    # ── Cambodia ──────────────────────────────────────────────────────────────
    "kh": "Cambodia", "khm": "Cambodia", "cambodia": "Cambodia",

    # ── Myanmar ───────────────────────────────────────────────────────────────
    "mm": "Myanmar", "mmr": "Myanmar", "myanmar": "Myanmar",
    "burma": "Myanmar",

    # ── Brunei ────────────────────────────────────────────────────────────────
    "bn": "Brunei", "brn": "Brunei", "brunei": "Brunei",

    # ── Laos ──────────────────────────────────────────────────────────────────
    # "la" omitted: conflicts with Louisiana (US state) which takes priority.
    "lao": "Laos", "laos": "Laos",

    # ── Malta ─────────────────────────────────────────────────────────────────
    # "mt" omitted: conflicts with Montana (US state) which takes priority.
    "mlt": "Malta", "malta": "Malta",

    # ── Papua New Guinea ──────────────────────────────────────────────────────
    "pg": "Papua New Guinea", "png": "Papua New Guinea",
    "papua new guinea": "Papua New Guinea",

    # ── Saudi Arabia ──────────────────────────────────────────────────────────
    # "sa" omitted: conflicts with South Australia which takes priority.
    "sau": "Saudi Arabia", "saudi arabia": "Saudi Arabia",
    "ksa": "Saudi Arabia",

    # ── Israel ────────────────────────────────────────────────────────────────
    # "il" omitted: conflicts with Illinois (US state) which takes priority.
    "isr": "Israel", "israel": "Israel",

    # ── Russia ────────────────────────────────────────────────────────────────
    "ru": "Russia", "rus": "Russia", "russia": "Russia",

    # ── Ukraine ───────────────────────────────────────────────────────────────
    "ua": "Ukraine", "ukr": "Ukraine", "ukraine": "Ukraine",

    # ── Romania ───────────────────────────────────────────────────────────────
    "ro": "Romania", "rou": "Romania", "romania": "Romania",

    # ── Czech Republic ────────────────────────────────────────────────────────
    "cz": "Czech Republic", "cze": "Czech Republic",
    "czech republic": "Czech Republic", "czechia": "Czech Republic",

    # ── Hungary ───────────────────────────────────────────────────────────────
    "hu": "Hungary", "hun": "Hungary", "hungary": "Hungary",

    # ── Croatia ───────────────────────────────────────────────────────────────
    "hr": "Croatia", "hrv": "Croatia", "croatia": "Croatia",

    # ── Slovakia ──────────────────────────────────────────────────────────────
    # "sk" omitted: conflicts with Saskatchewan (Canada) which takes priority.
    "svk": "Slovakia", "slovakia": "Slovakia",

    # ── Serbia ────────────────────────────────────────────────────────────────
    "rs": "Serbia", "srb": "Serbia", "serbia": "Serbia",

    # ── Morocco ───────────────────────────────────────────────────────────────
    # "ma" omitted: conflicts with Massachusetts (US state) which takes priority.
    "mar": "Morocco", "morocco": "Morocco",

    # ── Tanzania ──────────────────────────────────────────────────────────────
    "tz": "Tanzania", "tza": "Tanzania", "tanzania": "Tanzania",

    # ── Uganda ────────────────────────────────────────────────────────────────
    "ug": "Uganda", "uga": "Uganda", "uganda": "Uganda",

    # ── Zimbabwe ──────────────────────────────────────────────────────────────
    "zw": "Zimbabwe", "zwe": "Zimbabwe", "zimbabwe": "Zimbabwe",

    # ── Venezuela ─────────────────────────────────────────────────────────────
    "ve": "Venezuela", "ven": "Venezuela", "venezuela": "Venezuela",

    # ── Ecuador ───────────────────────────────────────────────────────────────
    "ec": "Ecuador", "ecu": "Ecuador", "ecuador": "Ecuador",

    # ── Bolivia ───────────────────────────────────────────────────────────────
    "bo": "Bolivia", "bol": "Bolivia", "bolivia": "Bolivia",

    # ── Paraguay ──────────────────────────────────────────────────────────────
    "py": "Paraguay", "pry": "Paraguay", "paraguay": "Paraguay",

    # ── Uruguay ───────────────────────────────────────────────────────────────
    "uy": "Uruguay", "ury": "Uruguay", "uruguay": "Uruguay",

    # ── Guatemala ─────────────────────────────────────────────────────────────
    "gt": "Guatemala", "gtm": "Guatemala", "guatemala": "Guatemala",

    # ── Costa Rica ────────────────────────────────────────────────────────────
    "cr": "Costa Rica", "cri": "Costa Rica", "costa rica": "Costa Rica",
}

# Two-letter codes that are ambiguous between countries (e.g. "ca" = California
# OR Canada, "in" = Indiana OR India, "id" = Idaho OR Indonesia).
# These are resolved by context elsewhere; the aliases above make a best-guess
# choice — US states take priority because FB's US address format is most common.
# Add explicit overrides here if a specific scraper needs different behaviour.


def normalize_country(raw: str) -> str:
    """Return a canonical country name for a raw location string.

    Falls back to title-casing the input if no alias matches, so unknown
    countries still get consistent capitalisation.
    """
    if not raw:
        return ""
    key = raw.strip().lower()
    return _ALIASES.get(key, raw.strip().title())


def has_alias(raw: str) -> bool:
    """Return True if raw has an explicit entry in the alias table."""
    return raw.strip().lower() in _ALIASES


_geocode_cache: dict[str, str] = {}


def _nominatim_lookup(query: str, timeout: int) -> str:
    import urllib.request
    import urllib.parse
    import json

    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "addressdetails": "1",
            "limit": "1",
            "accept-language": "en",
        })
    )
    req = urllib.request.Request(url, headers={"User-Agent": "veent-event-scraper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        results = json.loads(resp.read())
    if results:
        return results[0].get("address", {}).get("country", "")
    return ""


def geocode_country(query: str, *, timeout: int = 15) -> str:
    """Look up the country for a location string via Nominatim (OpenStreetMap).

    Returns the English country name, or "" on failure.
    Rate-limited to 1 req/s by the caller — this function does not sleep.
    Results are cached in-process to avoid duplicate calls within a run.

    If the full query string has no result, retries with progressively shorter
    trailing sub-queries (e.g. "Camp Aguinaldo, Quezon City" → "Quezon City").
    """
    query = query.strip()
    if not query:
        return ""
    if query in _geocode_cache:
        return _geocode_cache[query]

    # Build candidate queries: full string first, then trimming one leading segment at a time.
    parts = [p.strip() for p in query.split(",")]
    candidates = [query]
    for i in range(1, len(parts)):
        candidates.append(", ".join(parts[i:]))

    for i, candidate in enumerate(candidates):
        if candidate in _geocode_cache:
            result = _geocode_cache[candidate]
            if result:
                _geocode_cache[query] = result
                return result
            continue
        if i > 0:
            import time as _time
            _time.sleep(1)
        try:
            result = _nominatim_lookup(candidate, timeout)
            _geocode_cache[candidate] = result
            if result:
                _geocode_cache[query] = result
                return result
        except Exception:
            _geocode_cache[candidate] = ""

    _geocode_cache[query] = ""
    return ""
