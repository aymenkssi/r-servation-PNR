"""Tâche planifiée : marque comme expirées les options arrivées à échéance.

Prochaine étape (validité 7/14 jours) : recréer automatiquement une option
avant l'échéance et renvoyer le nouveau PNR au client.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from .models import Booking, get_engine, utcnow

log = logging.getLogger("scheduler")


def expire_bookings() -> int:
    with Session(get_engine()) as session:
        stale = session.exec(
            select(Booking).where(Booking.status == "held", Booking.expires_at < utcnow())
        ).all()
        for b in stale:
            b.status = "expired"
            session.add(b)
        session.commit()
        if stale:
            log.info("%d réservation(s) expirée(s)", len(stale))
        return len(stale)


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(expire_bookings, "interval", minutes=10, id="expire_bookings")
    sched.start()
    return sched
