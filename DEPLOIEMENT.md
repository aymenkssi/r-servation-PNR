# Déploiement — visaflight.creationapp.academy

Même architecture que le portfolio : le conteneur VisaFlight tourne derrière le Traefik déjà en
place sur le VPS, qui gère HTTPS et le certificat Let's Encrypt.

```
GitHub (r-servation-pnr) ──git pull──▶ VPS /opt/apps/visaflight ──docker compose──▶ uvicorn :8000
                                                              ▲
                visiteur ──HTTPS──▶ Traefik (websecure, letsencrypt)
```

## 1. DNS

Dans la zone DNS de **creationapp.academy** :

| Type | Nom | Valeur |
|---|---|---|
| A | `visaflight` | IPv4 du VPS |
| AAAA | `visaflight` | IPv6 du VPS, seulement si Traefik écoute en IPv6 |

```bash
dig +short visaflight.creationapp.academy A    # doit renvoyer l'IP du VPS avant l'étape 4
```

## 2. Récupérer le code sur le VPS

**Dépôt public (état actuel)** :

```bash
git clone https://github.com/aymenkssi/r-servation-pnr.git /opt/apps/visaflight
cd /opt/apps/visaflight
```

**Si vous passez le dépôt en privé (recommandé)**, utilisez une clé de déploiement en lecture
seule, comme pour le portfolio :

```bash
ssh-keygen -t ed25519 -N "" -C "vps-deploy visaflight" -f /root/.ssh/visaflight_deploy
cat /root/.ssh/visaflight_deploy.pub   # GitHub → r-servation-pnr → Settings → Deploy keys (sans écriture)

cat >> /root/.ssh/config <<'CONF'
Host github-visaflight
    HostName github.com
    User git
    IdentityFile /root/.ssh/visaflight_deploy
    IdentitiesOnly yes
    BatchMode yes
CONF
ssh -T github-visaflight
git clone github-visaflight:aymenkssi/r-servation-pnr.git /opt/apps/visaflight
# ou, si déjà cloné en HTTPS :
# git -C /opt/apps/visaflight remote set-url origin github-visaflight:aymenkssi/r-servation-pnr.git
```

## 3. Configurer

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

- `DUFFEL_ACCESS_TOKEN` : votre jeton `duffel_test_…` (vide = mode simulé).
- `SMTP_*` : facultatif ; sans SMTP, les e-mails apparaissent dans `docker compose logs`.
- Les variables `TRAEFIK_*` reprennent les valeurs du portfolio (`web`, `websecure`, `letsencrypt`).

## 4. Premier lancement

```bash
docker compose up -d --build
docker compose ps            # « healthy » au bout de 30 s environ
docker compose logs -f web
```

## 5. Vérifier

```bash
curl -I http://visaflight.creationapp.academy           # 301/308 vers https://
curl -I https://visaflight.creationapp.academy          # 200, Content-Security-Policy, Strict-Transport-Security
curl https://visaflight.creationapp.academy/healthz     # {"ok":true}
curl -I https://visaflight.creationapp.academy/docs     # 404 (documentation API désactivée)
```

Puis, dans un navigateur, faites une réservation de bout en bout (avec un jeton de test : JFK → EWR).

## 6. Mettre à jour

```bash
cd /opt/apps/visaflight && ./deploy.sh          # pull, rebuild, healthcheck, retour arrière auto
./deploy.sh --force                              # après une modification de .env
```

## 7. Données et sauvegarde

La base SQLite est dans le volume Docker `visaflight_visaflight-data`. Sauvegarde :

```bash
docker run --rm -v visaflight_visaflight-data:/d -v "$PWD":/b alpine \
  cp /d/app.db /b/app-$(date +%F).db
```

Elle contient des noms et dates de naissance : gardez les sauvegardes hors du dépôt.

## 8. Dépannage

| Symptôme | Cause probable | Vérification |
|---|---|---|
| Certificat « TRAEFIK DEFAULT CERT » | DNS pas propagé ou mauvais certresolver | `dig`, `docker logs traefik 2>&1 \| grep -i acme` |
| 404 de Traefik | Conteneur hors du réseau `web` | `docker inspect visaflight-web-1 \| grep -A3 Networks` |
| 502 / 504 | Conteneur non sain | `docker compose ps`, `docker compose logs web` |
| Erreur « La recherche a échoué » | Jeton Duffel invalide ou sortie HTTPS bloquée | `docker compose logs web` |
