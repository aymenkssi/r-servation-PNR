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

import phonenumbers
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .config import get_settings
from .countries import COUNTRIES
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
COUNTRY_CODES = {c[0] for c in COUNTRIES}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sched = None if os.getenv("DISABLE_SCHEDULER") else start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Réservation de vol pour visa", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

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
    ctx.update(app_name=s.app_name, mock_mode=s.mock_mode, test_mode=s.duffel_test_mode,
               test_zz_only=s.duffel_test_mode and s.test_hold_duffel_airways_only)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html", form={}, today=date.today().isoformat())


def place_label(p: dict) -> str:
    code = p["iata_code"]
    if p.get("type") == "city":
        return f"{p['name']} — tous les aéroports ({code})"
    city = p.get("city_name") or (p.get("city") or {}).get("name")
    name = p["name"]
    if city and city.lower() not in name.lower():
        name = f"{city}, {name}"
    return f"{name} ({code})"


def suggest(query: str) -> list[dict]:
    """Villes et aéroports correspondant à la saisie, villes en premier."""
    places = get_client().suggest_places(query)
    places = [p for p in places if p.get("iata_code") and p.get("type") in ("city", "airport")]
    return [
        {"code": p["iata_code"], "type": p["type"], "label": place_label(p),
         "country": p.get("iata_country_code")}
        for p in places[:8]
    ]


@app.get("/api/places")
def api_places(q: str = ""):
    q = q.strip()
    if len(q) < 2 or len(q) > 60:
        return JSONResponse([])
    try:
        return JSONResponse(suggest(q))
    except DuffelError as e:
        log.warning("Suggestions Duffel échouées : %s", e)
        return JSONResponse([], status_code=502)


def resolve_place(code: str, query: str) -> tuple[str | None, str]:
    """Code choisi dans la liste, sinon meilleur résultat pour le texte saisi."""
    code = code.strip().upper()
    query = query.strip()
    if IATA_RE.match(code):
        return code, query or code
    if not query:
        return None, query
    results = suggest(query)
    if not results:
        return None, query
    return results[0]["code"], results[0]["label"]


@app.post("/search", response_class=HTMLResponse)
def search(
    request: Request,
    origin_query: str = Form(""),
    origin: str = Form(""),
    destination_query: str = Form(""),
    destination: str = Form(""),
    departure_date: str = Form(...),
    return_date: str = Form(""),
):
    form = {
        "origin_query": origin_query, "origin": origin,
        "destination_query": destination_query, "destination": destination,
        "departure_date": departure_date, "return_date": return_date,
    }
    ctx = dict(form=form, today=date.today().isoformat())
    try:
        o_code, o_label = resolve_place(origin, origin_query)
        d_code, d_label = resolve_place(destination, destination_query)
    except DuffelError as e:
        return render(request, "index.html", 502, error=f"Recherche de ville impossible. {e.user_message()}", **ctx)
    form.update(origin=o_code or "", destination=d_code or "", origin_query=o_label, destination_query=d_label)

    error = None
    if not o_code:
        error = f"Ville ou aéroport de départ introuvable : « {origin_query} »."
    elif not d_code:
        error = f"Ville ou aéroport d'arrivée introuvable : « {destination_query} »."
    elif o_code == d_code:
        error = "Le départ et l'arrivée doivent être différents."
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
        return render(request, "index.html", 422, error=error, **ctx)

    slices = [{"origin": o_code, "destination": d_code, "departure_date": departure_date}]
    if return_date:
        slices.append({"origin": d_code, "destination": o_code, "departure_date": return_date})

    try:
        result = get_client().search(slices)
    except DuffelError as e:
        return render(request, "index.html", 502, error=f"La recherche a échoué. {e.user_message()}", **ctx)

    offers = [o for o in result.get("offers", []) if is_holdable(o)]
    settings = get_settings()
    test_filtered = settings.duffel_test_mode and settings.test_hold_duffel_airways_only
    if test_filtered:
        offers = [o for o in offers if o["owner"]["iata_code"] == "ZZ"]
    offers.sort(key=lambda o: float(o["total_amount"]))
    return render(request, "offers.html", form=form, offers=offers[:20], test_filtered=test_filtered,
                  excluded=len(result.get("offers", [])) - len(offers))


def passenger_ctx(offer: dict, form: dict) -> dict:
    origin_country = (offer["slices"][0]["origin"].get("iata_country_code") or "FR").upper()
    form.setdefault("phone_country", origin_country if origin_country in COUNTRY_CODES else "FR")
    return dict(offer=offer, form=form, countries=COUNTRIES)


def normalize_phone(number: str, country: str) -> str | None:
    """Renvoie le numéro au format E.164 (exigé par Duffel), ou None s'il est invalide."""
    try:
        parsed = phonenumbers.parse(number, country)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


@app.get("/offers/{offer_id}", response_class=HTMLResponse)
def offer_page(request: Request, offer_id: str):
    try:
        offer = get_client().get_offer(offer_id)
    except DuffelError:
        raise HTTPException(404, "Offre introuvable ou expirée. Relancez une recherche.")
    if not is_holdable(offer):
        raise HTTPException(422, "Cette offre ne peut pas être mise en option.")
    return render(request, "passenger.html", **passenger_ctx(offer, {}))


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
    phone_country: str = Form("FR"),
    phone_number: str = Form(...),
    session: Session = Depends(get_session),
):
    client = get_client()
    form = dict(title=title, gender=gender, given_name=given_name.strip(), family_name=family_name.strip(),
                born_on=born_on, email=email.strip(), phone_number=phone_number.strip())
    phone_country = phone_country.upper() if phone_country.upper() in COUNTRY_CODES else "FR"
    try:
        offer = client.get_offer(offer_id)
    except DuffelError:
        raise HTTPException(404, "Offre introuvable ou expirée. Relancez une recherche.")

    error = None
    if title not in {"mr", "ms", "mrs", "miss"} or gender not in {"m", "f"}:
        error = "Civilité invalide."
    elif not form["given_name"] or not form["family_name"]:
        error = "Le prénom et le nom sont obligatoires (comme sur le passeport)."
    elif not (e164 := normalize_phone(form["phone_number"], phone_country)):
        error = "Numéro de téléphone invalide pour le pays choisi."
    elif "@" not in form["email"]:
        error = "Adresse e-mail invalide."
    else:
        try:
            if date.fromisoformat(born_on) >= date.today():
                error = "Date de naissance invalide."
        except ValueError:
            error = "Date de naissance invalide."
    if error:
        return render(request, "passenger.html", 422, error=error,
                      **passenger_ctx(offer, {**form, "phone_country": phone_country}))

    passenger = {"id": offer["passengers"][0]["id"], **form, "phone_number": e164}
    try:
        order = client.create_hold_order(offer_id, [passenger])
    except DuffelError as e:
        log.warning("Création de l'option échouée (offre %s, compagnie %s) : %s",
                    offer_id, offer.get("owner", {}).get("iata_code"), e)
        return render(request, "passenger.html", 502, error=e.user_message(),
                      **passenger_ctx(offer, {**form, "phone_country": phone_country}))

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
