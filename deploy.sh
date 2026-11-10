#!/usr/bin/env bash
# Met à jour VisaFlight sur le VPS depuis GitHub, avec retour arrière automatique.
#   ./deploy.sh           déploie si origin/main a de nouveaux commits
#   ./deploy.sh --force   reconstruit et redéploie même sans nouveau commit
set -euo pipefail
cd "$(dirname "$0")"

IMAGE=visaflight
[ -f .env ] || { echo "Fichier .env absent : cp .env.example .env"; exit 1; }

# Jamais de demande d'identifiant interactive : on échoue avec un message clair.
export GIT_TERMINAL_PROMPT=0
if ! git fetch --quiet origin main; then
  echo "Impossible de lire le dépôt sur GitHub (dépôt privé sans clé de déploiement ?)."
  echo "Configurer la clé de déploiement : voir DEPLOIEMENT.md, étape 3."
  exit 1
fi
OLD=$(git rev-parse --short HEAD)
NEW=$(git rev-parse --short origin/main)
if [ "$OLD" = "$NEW" ] && [ "${1:-}" != "--force" ]; then
  echo "Déjà à jour ($OLD)."
  exit 0
fi

# --ff-only : refuse de déployer si des fichiers ont été modifiés à la main sur le VPS.
git merge --ff-only --quiet origin/main

# Garde l'image en service pour pouvoir y revenir.
HAS_PREV=0
if docker image inspect "$IMAGE:latest" >/dev/null 2>&1; then
  docker tag "$IMAGE:latest" "$IMAGE:prev"
  HAS_PREV=1
fi

docker compose up -d --build

echo "Attente du healthcheck…"
STATUS=starting
for _ in $(seq 1 30); do
  STATUS=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q web)" 2>/dev/null || echo starting)
  [ "$STATUS" = healthy ] && break
  sleep 3
done

if [ "$STATUS" != healthy ]; then
  echo "Le conteneur n'est pas sain ($STATUS)."
  docker compose logs --tail=30 web || true
  if [ "$HAS_PREV" = 1 ]; then
    echo "Retour à l'image précédente."
    docker tag "$IMAGE:prev" "$IMAGE:latest"
    docker compose up -d --no-build
    git reset --quiet --hard "$OLD"
  fi
  exit 1
fi

echo "Déployé : $OLD -> $(git log -1 --format='%h %s')"
