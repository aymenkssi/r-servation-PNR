import os
import re
from datetime import date, timedelta

os.environ["DUFFEL_ACCESS_TOKEN"] = ""  # mode simulé
os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
os.environ["DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, normalize_phone  # noqa: E402
from app.scheduler import expire_bookings  # noqa: E402


def _future(days):
    return (date.today() + timedelta(days=days)).isoformat()


def _search(c, **kw):
    data = {"origin_query": "", "origin": "", "destination_query": "", "destination": "",
            "departure_date": _future(30), "return_date": ""}
    data.update(kw)
    return c.post("/search", data=data)


def test_full_hold_flow():
    with TestClient(app) as c:
        assert c.get("/").status_code == 200

        r = _search(c, origin_query="Tunis-Carthage (TUN)", origin="TUN",
                    destination_query="Paris", destination="PAR", return_date=_future(40))
        assert r.status_code == 200
        offer_ids = re.findall(r"/offers/(off_\w+)", r.text)
        assert len(offer_ids) == 3  # l'offre à paiement immédiat est écartée

        r = c.get(f"/offers/{offer_ids[0]}")
        assert r.status_code == 200 and "Informations du passager" in r.text
        # Pays de l'indicatif présélectionné d'après l'aéroport de départ (Tunisie)
        assert re.search(r'value="TN" data-dial="216" selected', r.text)

        r = c.post("/book", data={
            "offer_id": offer_ids[0], "title": "mr", "gender": "m", "given_name": "Aymen",
            "family_name": "Dridi", "born_on": "1985-01-01", "email": "test@example.com",
            "phone_country": "FR", "phone_number": "06 12 34 56 78",
        }, follow_redirects=False)
        assert r.status_code == 303
        page = c.get(r.headers["location"])
        assert page.status_code == 200 and "Réservation créée" in page.text

        pdf = c.get(r.headers["location"] + "/pdf")
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")

        assert expire_bookings() == 0  # option encore valable


def test_search_by_city_name_without_selection():
    with TestClient(app) as c:
        # Texte libre sans choix dans la liste : la ville est résolue côté serveur
        r = _search(c, origin_query="djerba", destination_query="lyon")
        assert r.status_code == 200
        assert "DJE → LYS" in r.text


def test_places_api():
    with TestClient(app) as c:
        data = c.get("/api/places", params={"q": "paris"}).json()
        assert data[0]["code"] == "PAR" and data[0]["type"] == "city"
        assert {"CDG", "ORY"} <= {d["code"] for d in data}
        assert c.get("/api/places", params={"q": "seville"}).json()[0]["code"] == "SVQ"  # sans accent
        assert c.get("/api/places", params={"q": "p"}).json() == []


def test_validation_errors():
    with TestClient(app) as c:
        r = _search(c, origin_query="Atlantide", destination_query="Paris")
        assert r.status_code == 422 and "introuvable" in r.text
        r = _search(c, origin="TUN", destination="CDG", departure_date="2020-01-01")
        assert r.status_code == 422
        r = _search(c, origin_query="Paris", destination_query="Paris")
        assert r.status_code == 422


def test_phone_normalization():
    assert normalize_phone("06 12 34 56 78", "FR") == "+33612345678"
    assert normalize_phone("+33 6 12 34 56 78", "FR") == "+33612345678"
    assert normalize_phone("+216 98 123 456", "TN") == "+21698123456"
    assert normalize_phone("98123456", "TN") == "+21698123456"
    assert normalize_phone("12", "FR") is None


def test_bad_phone_rejected():
    with TestClient(app) as c:
        r = _search(c, origin="TUN", destination="CDG")
        offer_id = re.findall(r"/offers/(off_\w+)", r.text)[0]
        r = c.post("/book", data={
            "offer_id": offer_id, "title": "ms", "gender": "f", "given_name": "A", "family_name": "B",
            "born_on": "1990-05-05", "email": "a@b.co", "phone_country": "FR", "phone_number": "+33 12",
        })
        assert r.status_code == 422 and "téléphone invalide" in r.text


def test_duffel_error_messages():
    from app.duffel import DuffelError
    e = DuffelError("Something went wrong", 500, [{"code": "internal_server_error"}], "req_ABC")
    assert "Choisissez un autre vol" in e.user_message() and "req_ABC" in e.user_message()
    e = DuffelError("gone", 422, [{"code": "offer_no_longer_available"}])
    assert "plus disponible" in e.user_message()
    e = DuffelError("bad", 422, [{"code": "validation_error", "message": "born_on is invalid"}])
    assert "born_on is invalid" in e.user_message()


def test_duffel_client_parses_error_body():
    import httpx
    import pytest
    from app.config import Settings
    from app.duffel import DuffelClient, DuffelError

    def handler(request):
        return httpx.Response(500, json={
            "meta": {"status": 500, "request_id": "FzX123"},
            "errors": [{"type": "api_error", "code": "internal_server_error",
                        "message": "Something went wrong."}]})

    client = DuffelClient(Settings(duffel_access_token="duffel_test_x"))
    client._http = httpx.Client(base_url="https://api.duffel.com", transport=httpx.MockTransport(handler))
    with pytest.raises(DuffelError) as exc:
        client.create_hold_order("off_1", [])
    assert exc.value.status == 500 and exc.value.request_id == "FzX123"
    assert "FzX123" in exc.value.user_message()


def test_test_mode_filters_airlines(monkeypatch):
    import app.main as m
    from app.config import Settings
    monkeypatch.setattr(m, "get_settings", lambda: Settings(duffel_access_token="duffel_test_x"))
    with TestClient(app) as c:
        r = _search(c, origin="JFK", destination="EWR")
        assert r.status_code == 200
        assert len(re.findall(r"/offers/(off_\w+)", r.text)) == 1
        assert "Duffel Airways" in r.text and "Air France" not in r.text
    monkeypatch.setattr(m, "get_settings", lambda: Settings(duffel_access_token="duffel_test_x",
                                                            test_hold_airlines=""))
    with TestClient(app) as c:
        r = _search(c, origin="JFK", destination="EWR")
        assert len(re.findall(r"/offers/(off_\w+)", r.text)) == 3  # filtre désactivé
