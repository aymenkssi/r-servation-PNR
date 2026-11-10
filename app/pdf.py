"""Génération du PDF d'itinéraire (bilingue FR/EN)."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import get_settings

NAVY = colors.HexColor("#1e3a8a")
LIGHT = colors.HexColor("#eef2ff")


def _fmt(dt_str: str | None, with_time: bool = True) -> str:
    if not dt_str:
        return "-"
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return dt.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def build_itinerary_pdf(order: dict, expires_at: str | None = None) -> bytes:
    settings = get_settings()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Itinéraire {order['booking_reference']}",
    )
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, alignment=0, fontSize=20)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, spaceBefore=8)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8.5, textColor=colors.grey)
    normal = ss["Normal"]

    story = [
        Paragraph(settings.app_name, h1),
        Paragraph("Itinéraire de réservation / Flight reservation itinerary", normal),
        Spacer(1, 6 * mm),
    ]

    pnr_table = Table(
        [
            ["Référence de réservation (PNR)\nBooking reference", order["booking_reference"]],
            ["Compagnie / Airline", f"{order['owner']['name']} ({order['owner']['iata_code']})"],
            ["Statut / Status", "Réservé — billet non émis / Booked — ticket not issued"],
            ["Valable jusqu'au (UTC) / Valid until (UTC)", _fmt(expires_at)],
            ["Date d'émission / Issued on", _fmt(order.get("created_at"))],
        ],
        colWidths=[70 * mm, 104 * mm],
    )
    pnr_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (1, 0), (1, 0), 16),
        ("TEXTCOLOR", (1, 0), (1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("FONTSIZE", (0, 0), (0, -1), 8.5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [pnr_table, Paragraph("Passager(s) / Passenger(s)", h2)]

    pax_rows = [["Nom / Name", "Date de naissance / Date of birth"]]
    for p in order.get("passengers", []):
        name = f"{p.get('title', '').upper()} {p.get('given_name', '')} {p.get('family_name', '').upper()}".strip()
        pax_rows.append([name, _fmt(p.get("born_on"), with_time=False)])
    pax = Table(pax_rows, colWidths=[110 * mm, 64 * mm])
    pax.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story += [pax, Paragraph("Vols / Flights", h2)]

    seg_rows = [["Vol / Flight", "De / From", "À / To", "Départ / Departure", "Arrivée / Arrival"]]
    for sl in order.get("slices", []):
        for seg in sl.get("segments", []):
            carrier = seg.get("marketing_carrier", {})
            seg_rows.append([
                f"{carrier.get('iata_code', '')} {seg.get('marketing_carrier_flight_number', '')}",
                seg["origin"]["iata_code"],
                seg["destination"]["iata_code"],
                _fmt(seg.get("departing_at")),
                _fmt(seg.get("arriving_at")),
            ])
    segs = Table(seg_rows, colWidths=[28 * mm, 22 * mm, 22 * mm, 51 * mm, 51 * mm])
    segs.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story += [segs, Spacer(1, 8 * mm)]

    story.append(Paragraph(
        "Vérification : saisissez la référence et le nom du passager dans la rubrique "
        "« Gérer ma réservation » du site de la compagnie. Cette réservation est temporaire "
        "et sera annulée automatiquement par la compagnie après la date de validité. "
        "<br/>Verification: enter the booking reference and passenger surname in the airline's "
        "“Manage booking” page. This reservation is temporary and will be cancelled by the "
        "airline after the validity date.",
        small,
    ))

    doc.build(story)
    return buf.getvalue()
