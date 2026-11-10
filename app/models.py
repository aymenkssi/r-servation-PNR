from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, create_engine

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Booking(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, unique=True)  # identifiant non devinable pour les liens
    duffel_order_id: str = Field(index=True)
    booking_reference: str  # PNR
    airline_name: str
    airline_iata: str
    email: str
    passenger_name: str
    expires_at: datetime | None = None  # échéance de l'option (UTC)
    status: str = "held"  # held | expired | cancelled
    order_json: str  # réponse Duffel complète
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def order(self) -> dict:
        return json.loads(self.order_json)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///./"):
            os.makedirs(os.path.dirname(url.removeprefix("sqlite:///")) or ".", exist_ok=True)
        _engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session
