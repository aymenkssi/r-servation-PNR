"""Client minimal pour l'API Duffel v2 (recherche, offre, commande en option).

Sans jeton (DUFFEL_ACCESS_TOKEN vide), un client simulé renvoie des
réponses de même forme que l'API, pour développer hors ligne.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import places_mock
from .config import Settings, get_settings


class DuffelError(Exception):
    def __init__(self, message: str, status: int | None = None, errors: list | None = None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


class DuffelClient:
    def __init__(self, settings: Settings):
        self._http = httpx.Client(
            base_url=settings.duffel_base_url,
            timeout=60,
            headers={
                "Authorization": f"Bearer {settings.duffel_access_token}",
                "Duffel-Version": settings.duffel_version,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                errors = resp.json().get("errors", [])
            except ValueError:
                errors = []
            msg = "; ".join(e.get("message", "") for e in errors) or resp.text[:300]
            raise DuffelError(msg, resp.status_code, errors)
        return resp.json()["data"]

    def search(self, slices: list[dict], adults: int = 1, cabin_class: str = "economy") -> dict:
        body = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(adults)],
                "cabin_class": cabin_class,
            }
        }
        return self._request(
            "POST", "/air/offer_requests", params={"return_offers": "true"}, json=body
        )

    def get_offer(self, offer_id: str) -> dict:
        return self._request("GET", f"/air/offers/{offer_id}")

    def create_hold_order(self, offer_id: str, passengers: list[dict]) -> dict:
        body = {
            "data": {
                "type": "hold",
                "selected_offers": [offer_id],
                "passengers": passengers,
            }
        }
        return self._request("POST", "/air/orders", json=body)

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/air/orders/{order_id}")

    def suggest_places(self, query: str) -> list[dict]:
        return self._request("GET", "/places/suggestions", params={"query": query})


# --------------------------------------------------------------------------
# Client simulé
# --------------------------------------------------------------------------

def _rid(prefix: str, n: int = 22) -> str:
    return prefix + "".join(random.choices(string.ascii_letters + string.digits, k=n))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


_MOCK_CARRIERS = [
    ("ZZ", "Duffel Airways"),
    ("AF", "Air France"),
    ("TU", "Tunisair"),
    ("TK", "Turkish Airlines"),
]


class MockDuffelClient:
    """Imite les réponses Duffel. Les offres et commandes restent en mémoire."""

    def __init__(self):
        self._offers: dict[str, dict] = {}
        self._orders: dict[str, dict] = {}

    @staticmethod
    def _loc(code: str) -> dict:
        p = places_mock.BY_CODE.get(code, {})
        # Une ville est desservie par son premier aéroport.
        if p.get("type") == "city":
            code = p["airports"][0]["iata_code"]
            p = places_mock.BY_CODE.get(code, p)
        return {"iata_code": code, "name": p.get("name", code),
                "city_name": p.get("city_name", code), "iata_country_code": p.get("iata_country_code")}

    def suggest_places(self, query: str) -> list[dict]:
        return places_mock.suggest(query)

    def _segment(self, origin: str, destination: str, date: str, carrier: tuple[str, str]) -> dict:
        dep = datetime.fromisoformat(date).replace(
            hour=random.choice([7, 9, 12, 15, 18]), minute=random.choice([0, 15, 30, 45])
        )
        arr = dep + timedelta(hours=random.randint(2, 6), minutes=random.choice([0, 20, 40]))
        return {
            "origin": self._loc(origin),
            "destination": self._loc(destination),
            "departing_at": dep.strftime("%Y-%m-%dT%H:%M:%S"),
            "arriving_at": arr.strftime("%Y-%m-%dT%H:%M:%S"),
            "marketing_carrier": {"iata_code": carrier[0], "name": carrier[1]},
            "marketing_carrier_flight_number": str(random.randint(100, 9999)),
        }

    def search(self, slices: list[dict], adults: int = 1, cabin_class: str = "economy") -> dict:
        now = datetime.now(timezone.utc)
        passengers = [{"id": _rid("pas_"), "type": "adult"} for _ in range(adults)]
        offers = []
        for i, carrier in enumerate(_MOCK_CARRIERS):
            offer = {
                "id": _rid("off_"),
                "total_amount": f"{random.randint(90, 650)}.{random.randint(0, 99):02d}",
                "total_currency": "EUR",
                "owner": {"iata_code": carrier[0], "name": carrier[1]},
                "expires_at": _iso(now + timedelta(minutes=30)),
                "passengers": passengers,
                "payment_requirements": {
                    # Une offre sur quatre exige un paiement immédiat (non éligible).
                    "requires_instant_payment": i == 3,
                    "payment_required_by": None if i == 3 else _iso(now + timedelta(hours=48)),
                    "price_guarantee_expires_at": None,
                },
                "slices": [
                    {
                        "origin": self._loc(s["origin"]),
                        "destination": self._loc(s["destination"]),
                        "segments": [
                            self._segment(s["origin"], s["destination"], s["departure_date"], carrier)
                        ],
                    }
                    for s in slices
                ],
            }
            self._offers[offer["id"]] = offer
            offers.append(offer)
        return {"id": _rid("orq_"), "offers": offers, "passengers": passengers}

    def get_offer(self, offer_id: str) -> dict:
        if offer_id not in self._offers:
            raise DuffelError("Offre introuvable ou expirée", 404)
        return self._offers[offer_id]

    def create_hold_order(self, offer_id: str, passengers: list[dict]) -> dict:
        offer = self.get_offer(offer_id)
        if offer["payment_requirements"]["requires_instant_payment"]:
            raise DuffelError("Cette offre ne peut pas être mise en option", 422)
        now = datetime.now(timezone.utc)
        order = {
            "id": _rid("ord_"),
            "booking_reference": "".join(random.choices(string.ascii_uppercase + string.digits, k=6)),
            "created_at": _iso(now),
            "owner": offer["owner"],
            "total_amount": offer["total_amount"],
            "total_currency": offer["total_currency"],
            "slices": offer["slices"],
            "passengers": passengers,
            "payment_status": {
                "awaiting_payment": True,
                "payment_required_by": offer["payment_requirements"]["payment_required_by"],
            },
        }
        self._orders[order["id"]] = order
        return order

    def get_order(self, order_id: str) -> dict:
        if order_id not in self._orders:
            raise DuffelError("Commande introuvable", 404)
        return self._orders[order_id]


_client: DuffelClient | MockDuffelClient | None = None


def get_client() -> DuffelClient | MockDuffelClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = MockDuffelClient() if settings.mock_mode else DuffelClient(settings)
    return _client


def is_holdable(offer: dict) -> bool:
    req = offer.get("payment_requirements") or {}
    return req.get("requires_instant_payment") is False
