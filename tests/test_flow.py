import os
import re
from datetime import date, timedelta

os.environ["DUFFEL_ACCESS_TOKEN"] = ""  # mode simulé
os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"
os.environ["DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.scheduler import expire_bookings  # noqa: E402


def _future(days):
    return (date.today() + timedelta(days=days)).isoformat()


def test_full_hold_flow():
    with TestClient(app) as c:
        assert c.get("/").status_code == 200

        r = c.post("/search", data={"origin": "tun", "destination": "CDG",
                                    "departure_date": _future(30), "return_date": _future(40)})
        assert r.status_code == 200
        offer_ids = re.findall(r"/offers/(off_\w+)", r.text)
        assert len(offer_ids) == 3  # l'offre à paiement immédiat est écartée

        r = c.get(f"/offers/{offer_ids[0]}")
        assert r.status_code == 200 and "Informations du passager" in r.text

        r = c.post("/book", data={
            "offer_id": offer_ids[0], "title": "mr", "gender": "m", "given_name": "Aymen",
            "family_name": "Dridi", "born_on": "1985-01-01", "email": "test@example.com",
            "phone_number": "+33 6 12 34 56 78",
        }, follow_redirects=False)
        assert r.status_code == 303
        page = c.get(r.headers["location"])
        assert page.status_code == 200 and "Réservation créée" in page.text

        pdf = c.get(r.headers["location"] + "/pdf")
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")

        assert expire_bookings() == 0  # option encore valable


def test_validation_errors():
    with TestClient(app) as c:
        r = c.post("/search", data={"origin": "PARIS", "destination": "CDG", "departure_date": _future(5)})
        assert r.status_code == 422 and "IATA" in r.text
        r = c.post("/search", data={"origin": "TUN", "destination": "CDG", "departure_date": "2020-01-01"})
        assert r.status_code == 422


def test_bad_phone_rejected():
    with TestClient(app) as c:
        r = c.post("/search", data={"origin": "TUN", "destination": "CDG", "departure_date": _future(10)})
        offer_id = re.findall(r"/offers/(off_\w+)", r.text)[0]
        r = c.post("/book", data={
            "offer_id": offer_id, "title": "ms", "gender": "f", "given_name": "A", "family_name": "B",
            "born_on": "1990-05-05", "email": "a@b.co", "phone_number": "0612345678",
        })
        assert r.status_code == 422 and "international" in r.text
