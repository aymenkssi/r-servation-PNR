"""Application web : recherche → offre → passager → option (hold) → itinéraire PDF."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .config import get_settings
from .duffel import DuffelError, get_client, is_holdable
from .emailer import send_itinerary
from .models import Booking, get_session, init_db
from .pdf import build_itinerary_pdf
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

IATA_RE = re.compile(r"^[A-Z]{3}$")
PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")  # format E.164 exigé par Duffel


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sched = None if os.getenv("DISABLE_SCHEDULER") else start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Réservation de vol pour visa", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

# Tailwind est chargé depuis son CDN (MVP) : il injecte des styles inline.
CSP = (
    "default-src 'none'; script-src 'self' https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path.startswith("/booking/"):
        response.headers["Cache-Control"] = "no-store"  # données personnelles
        response.headers["X-Robots-Tag"] = "noindex"
    return response


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")


templates.env.filters["dt"] = fmt_dt


def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    s = get_settings()
    ctx.update(app_name=s.app_name, mock_mode=s.mock_mode, test_mode=s.duffel_test_mode)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html", form={}, today=date.today().isoformat())


@app.post("/search", response_class=HTMLResponse)
def search(
    request: Request,
    origin: str = Form(...),
    destination: str = Form(...),
    departure_date: str = Form(...),
    return_date: str = Form(""),
):
    form = {
        "origin": origin.strip().upper(),
        "destination": destination.strip().upper(),
        "departure_date": departure_date,
        "return_date": return_date,
    }
    error = None
    if not IATA_RE.match(form["origin"]) or not IATA_RE.match(form["destination"]):
        error = "Utilisez les codes IATA à 3 lettres (ex. TUN, CDG)."
    elif form["origin"] == form["destination"]:
        error = "L'origine et la destination doivent être différentes."
    else:
        try:
            dep = date.fromisoformat(departure_date)
            ret = date.fromisoformat(return_date) if return_date else None
            if dep <= date.today():
                error = "La date de départ doit être dans le futur."
            elif ret and ret < dep:
                error = "La date de retour doit être après la date de départ."
        except ValueError:
            error = "Date invalide."
    if error:
        return render(request, "index.html", 422, form=form, error=error, today=date.today().isoformat())

    slices = [{"origin": form["origin"], "destination": form["destination"], "departure_date": departure_date}]
    if return_date:
        slices.append({"origin": form["destination"], "destination": form["origin"], "departure_date": return_date})

    try:
        result = get_client().search(slices)
    except DuffelError as e:
        log.warning("Recherche Duffel échouée : %s", e)
        return render(request, "index.html", 502, form=form, today=date.today().isoformat(),
                      error=f"La recherche a échoué : {e}")

    offers = [o for o in result.get("offers", []) if is_holdable(o)]
    offers.sort(key=lambda o: float(o["total_amount"]))
    return render(request, "offers.html", form=form, offers=offers[:20],
                  excluded=len(result.get("offers", [])) - len(offers))


@app.get("/offers/{offer_id}", response_class=HTMLResponse)
def offer_page(request: Request, offer_id: str):
    try:
        offer = get_client().get_offer(offer_id)
    except DuffelError:
        raise HTTPException(404, "Offre introuvable ou expirée. Relancez une recherche.")
    if not is_holdable(offer):
        raise HTTPException(422, "Cette offre ne peut pas être mise en option.")
    return render(request, "passenger.html", offer=offer, form={})


@app.post("/book")
def book(
    request: Request,
    offer_id: str = Form(...),
    title: str = Form(...),
    gender: str = Form(...),
    given_name: str = Form(...),
    family_name: str = Form(...),
    born_on: str = Form(...),
    email: str = Form(...),
    phone_number: str = Form(...),
    session: Session = Depends(get_session),
):
    client = get_client()
    form = dict(title=title, gender=gender, given_name=given_name.strip(), family_name=family_name.strip(),
                born_on=born_on, email=email.strip(), phone_number=phone_number.replace(" ", ""))
    try:
        offer = client.get_offer(offer_id)
    except DuffelError:
        raise HTTPException(404, "Offre introuvable ou expirée. Relancez une recherche.")

    error = None
    if title not in {"mr", "ms", "mrs", "miss"} or gender not in {"m", "f"}:
        error = "Civilité invalide."
    elif not form["given_name"] or not form["family_name"]:
        error = "Le prénom et le nom sont obligatoires (comme sur le passeport)."
    elif not PHONE_RE.match(form["phone_number"]):
        error = "Téléphone au format international, ex. +33612345678."
    elif "@" not in form["email"]:
        error = "Adresse e-mail invalide."
    else:
        try:
            if date.fromisoformat(born_on) >= date.today():
                error = "Date de naissance invalide."
        except ValueError:
            error = "Date de naissance invalide."
    if error:
        return render(request, "passenger.html", 422, offer=offer, form=form, error=error)

    passenger = {"id": offer["passengers"][0]["id"], **form}
    try:
        order = client.create_hold_order(offer_id, [passenger])
    except DuffelError as e:
        log.warning("Création de l'option échouée : %s", e)
        return render(request, "passenger.html", 502, offer=offer, form=form,
                      error=f"La compagnie a refusé la réservation : {e}")

    expires = (order.get("payment_status") or {}).get("payment_required_by")
    booking = Booking(
        public_id=secrets.token_urlsafe(16),
        duffel_order_id=order["id"],
        booking_reference=order["booking_reference"],
        airline_name=order["owner"]["name"],
        airline_iata=order["owner"]["iata_code"],
        email=form["email"],
        passenger_name=f"{form['given_name']} {form['family_name']}",
        expires_at=datetime.fromisoformat(expires.replace("Z", "+00:00")) if expires else None,
        order_json=json.dumps(order),
    )
    session.add(booking)
    session.commit()

    link = f"{get_settings().base_url}/booking/{booking.public_id}"
    try:
        send_itinerary(booking.email, booking.booking_reference, build_itinerary_pdf(order, expires), link)
    except Exception:  # l'e-mail ne doit pas bloquer la réservation
        log.exception("Envoi de l'e-mail échoué")

    return RedirectResponse(f"/booking/{booking.public_id}", status_code=303)


def _get_booking(session: Session, public_id: str) -> Booking:
    booking = session.exec(select(Booking).where(Booking.public_id == public_id)).first()
    if not booking:
        raise HTTPException(404, "Réservation introuvable.")
    return booking


@app.get("/booking/{public_id}", response_class=HTMLResponse)
def booking_page(request: Request, public_id: str, session: Session = Depends(get_session)):
    booking = _get_booking(session, public_id)
    return render(request, "confirmation.html", booking=booking, order=booking.order)


@app.get("/booking/{public_id}/pdf")
def booking_pdf(public_id: str, session: Session = Depends(get_session)):
    booking = _get_booking(session, public_id)
    expires = (booking.order.get("payment_status") or {}).get("payment_required_by")
    pdf = build_itinerary_pdf(booking.order, expires)
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="itineraire-{booking.booking_reference}.pdf"'
    })
