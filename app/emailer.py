"""Envoi de l'e-mail de confirmation (SMTP, ou console si non configuré)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("emailer")


def send_itinerary(to: str, pnr: str, pdf: bytes, link: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = f"Votre réservation de vol — {pnr}"
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg.set_content(
        f"Bonjour,\n\nVotre réservation de vol est prête.\n"
        f"Référence (PNR) : {pnr}\n\n"
        f"Vous trouverez l'itinéraire en pièce jointe. Vous pouvez aussi le consulter ici :\n{link}\n\n"
        f"Vérifiez la réservation sur le site de la compagnie (« Gérer ma réservation »).\n\n"
        f"{s.app_name}"
    )
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"itineraire-{pnr}.pdf")

    if not s.smtp_host:
        log.warning("SMTP non configuré — e-mail non envoyé.\nÀ : %s\nObjet : %s\nLien : %s",
                    to, msg["Subject"], link)
        return

    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
