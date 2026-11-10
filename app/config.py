from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    duffel_access_token: str = ""
    duffel_base_url: str = "https://api.duffel.com"
    duffel_version: str = "v2"

    # Mode test : compagnies (codes IATA) dont la création d'option a été vérifiée.
    # Certaines compagnies simulées renvoient une erreur 500. Vide = aucun filtre.
    test_hold_airlines: str = "ZZ,BA"

    app_name: str = "VisaFlight"
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./data/app.db"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.com"

    @property
    def mock_mode(self) -> bool:
        """Sans jeton Duffel, l'application simule l'API."""
        return not self.duffel_access_token

    @property
    def test_airlines_filter(self) -> set[str]:
        """Codes des compagnies affichées en mode test (ensemble vide = toutes)."""
        if not self.duffel_test_mode:
            return set()
        return {c.strip().upper() for c in self.test_hold_airlines.split(",") if c.strip()}

    @property
    def duffel_test_mode(self) -> bool:
        return self.duffel_access_token.startswith("duffel_test_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
