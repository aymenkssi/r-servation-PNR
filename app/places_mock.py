"""Villes et aéroports du mode simulé (même forme que /places/suggestions de Duffel)."""
from __future__ import annotations

import unicodedata

# (type, code IATA, nom, ville, pays, codes des aéroports si ville)
_RAW = [
    ("city", "PAR", "Paris", "Paris", "FR", ["CDG", "ORY"]),
    ("airport", "CDG", "Paris-Charles de Gaulle", "Paris", "FR", None),
    ("airport", "ORY", "Paris-Orly", "Paris", "FR", None),
    ("airport", "BVA", "Beauvais-Tillé", "Beauvais", "FR", None),
    ("airport", "LYS", "Lyon-Saint Exupéry", "Lyon", "FR", None),
    ("airport", "MRS", "Marseille Provence", "Marseille", "FR", None),
    ("airport", "NCE", "Nice Côte d'Azur", "Nice", "FR", None),
    ("airport", "TLS", "Toulouse-Blagnac", "Toulouse", "FR", None),
    ("airport", "BOD", "Bordeaux-Mérignac", "Bordeaux", "FR", None),
    ("airport", "NTE", "Nantes Atlantique", "Nantes", "FR", None),
    ("airport", "TUN", "Tunis-Carthage", "Tunis", "TN", None),
    ("airport", "DJE", "Djerba-Zarzis", "Djerba", "TN", None),
    ("airport", "MIR", "Monastir Habib Bourguiba", "Monastir", "TN", None),
    ("airport", "NBE", "Enfidha-Hammamet", "Enfidha", "TN", None),
    ("airport", "SFA", "Sfax-Thyna", "Sfax", "TN", None),
    ("airport", "ALG", "Alger Houari Boumediene", "Alger", "DZ", None),
    ("airport", "ORN", "Oran Ahmed Ben Bella", "Oran", "DZ", None),
    ("airport", "CMN", "Casablanca Mohammed V", "Casablanca", "MA", None),
    ("airport", "RAK", "Marrakech Ménara", "Marrakech", "MA", None),
    ("city", "LON", "Londres", "Londres", "GB", ["LHR", "LGW", "STN"]),
    ("airport", "LHR", "Londres Heathrow", "Londres", "GB", None),
    ("airport", "LGW", "Londres Gatwick", "Londres", "GB", None),
    ("airport", "STN", "Londres Stansted", "Londres", "GB", None),
    ("city", "NYC", "New York", "New York", "US", ["JFK", "EWR", "LGA"]),
    ("airport", "JFK", "New York John F. Kennedy", "New York", "US", None),
    ("airport", "EWR", "Newark Liberty", "New York", "US", None),
    ("airport", "LGA", "New York LaGuardia", "New York", "US", None),
    ("city", "MIL", "Milan", "Milan", "IT", ["MXP", "LIN"]),
    ("airport", "MXP", "Milan Malpensa", "Milan", "IT", None),
    ("city", "ROM", "Rome", "Rome", "IT", ["FCO", "CIA"]),
    ("airport", "FCO", "Rome Fiumicino", "Rome", "IT", None),
    ("airport", "MAD", "Madrid-Barajas", "Madrid", "ES", None),
    ("airport", "BCN", "Barcelone-El Prat", "Barcelone", "ES", None),
    ("airport", "SVQ", "Séville", "Séville", "ES", None),
    ("airport", "AGP", "Malaga", "Malaga", "ES", None),
    ("airport", "FRA", "Francfort", "Francfort", "DE", None),
    ("airport", "BER", "Berlin Brandebourg", "Berlin", "DE", None),
    ("airport", "MUC", "Munich", "Munich", "DE", None),
    ("airport", "BRU", "Bruxelles", "Bruxelles", "BE", None),
    ("airport", "AMS", "Amsterdam Schiphol", "Amsterdam", "NL", None),
    ("airport", "GVA", "Genève", "Genève", "CH", None),
    ("airport", "ZRH", "Zurich", "Zurich", "CH", None),
    ("city", "IST", "Istanbul", "Istanbul", "TR", ["IST", "SAW"]),
    ("airport", "SAW", "Istanbul Sabiha Gökçen", "Istanbul", "TR", None),
    ("airport", "DXB", "Dubaï", "Dubaï", "AE", None),
    ("airport", "DOH", "Doha Hamad", "Doha", "QA", None),
    ("airport", "CAI", "Le Caire", "Le Caire", "EG", None),
    ("city", "YMQ", "Montréal", "Montréal", "CA", ["YUL"]),
    ("airport", "YUL", "Montréal-Trudeau", "Montréal", "CA", None),
    ("airport", "YYZ", "Toronto Pearson", "Toronto", "CA", None),
]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _place(t, code, name, city, country, airports):
    p = {"type": t, "iata_code": code, "name": name, "city_name": city, "iata_country_code": country}
    if t == "city":
        p["airports"] = [{"iata_code": a} for a in airports]
    return p


PLACES = [_place(*r) for r in _RAW]
BY_CODE = {}
for _p in PLACES:  # une ville et son aéroport principal peuvent partager un code (IST)
    BY_CODE.setdefault(_p["iata_code"], _p)


def suggest(query: str) -> list[dict]:
    q = _norm(query.strip())
    if not q:
        return []
    exact = [p for p in PLACES if p["iata_code"].lower() == q]
    starts = [p for p in PLACES if p not in exact and (
        _norm(p["name"]).startswith(q) or _norm(p["city_name"]).startswith(q))]
    contains = [p for p in PLACES if p not in exact and p not in starts and (
        q in _norm(p["name"]) or q in _norm(p["city_name"]))]
    return exact + starts + contains
