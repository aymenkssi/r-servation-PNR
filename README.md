# Réservation de vol pour visa (PNR vérifiable)

Application web FastAPI qui crée une **réservation de vol en option** (« hold order ») via l'API
[Duffel](https://duffel.com/docs/guides/holding-orders-and-paying-later) et génère un itinéraire PDF
avec le code PNR, vérifiable sur le site de la compagnie.

## Flux

1. Recherche (codes IATA, aller / retour)
2. Liste des offres **pouvant être mises en option** (`requires_instant_payment = false`)
3. Saisie du passager
4. Création de la commande `type: "hold"` (aucun paiement à la compagnie)
5. Page de confirmation + PDF + e-mail
6. Tâche planifiée qui marque les options expirées

## Démarrage

```bash
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # puis renseigner DUFFEL_ACCESS_TOKEN=duffel_test_...
uvicorn app.main:app --reload
```

Ouvrir http://localhost:8000.

- **Sans jeton** : mode simulé, aucune requête vers Duffel (utile pour développer l'interface).
- **Jeton `duffel_test_…`** : vraies requêtes en mode test. Pour obtenir une offre « holdable »,
  chercher **JFK → EWR** (compagnie fictive Duffel Airways).

## Tests

```bash
pytest -q
```

## Structure

```
app/
  main.py        routes FastAPI
  duffel.py      client API Duffel v2 + client simulé
  models.py      modèle Booking (SQLModel / SQLite)
  pdf.py         itinéraire PDF bilingue (ReportLab)
  emailer.py     envoi SMTP (ou console)
  scheduler.py   expiration des options (APScheduler)
  templates/     pages Jinja2 + Tailwind
tests/
```

## Prochaines étapes

- Paiement Stripe avant la création de l'option
- Validité 7 / 14 jours : recréer l'option avant échéance et renvoyer le nouveau PNR
- Option « recevoir plus tard » (création planifiée à une date choisie)
- Plusieurs passagers
- Confirmer auprès de Duffel que ce cas d'usage est autorisé avant le passage en production

> ⚠️ Ne jamais committer le fichier `.env` (il contient le jeton Duffel). Il est exclu par `.gitignore`.
