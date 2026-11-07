# Espace IA-IPR EPS

Première version du hub documentaire. Le dépôt public contient le code. Les comptes, les droits et les fichiers sont conservés dans une base SQLite sur le serveur de l’application.

## Essai local avec des données fictives

Python 3.12, Flask et Waitress. Pour lire les PDF dans le Hub, installez Poppler (`pdftoppm`). Les commandes suivantes s’exécutent dans le dossier du projet.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export HUB_LOCAL_HTTP=1
export HUB_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
flask --app app init-db --email animateur@example.test
waitress-serve --listen=127.0.0.1:8080 --call app:create_app
```

Ouvrez http://127.0.0.1:8080. La commande d’initialisation demande le mot de passe Animateur. La clé de session doit être conservée côté serveur entre les redémarrages.

## Organiser et partager

1. Dans **Documents**, créez une branche à la racine. Dans cette branche, **Ajouter un dossier** crée un sous-dossier. Répétez l’opération à chaque niveau voulu. L’animateur peut modifier la couleur d’un dossier.
2. Dans **Annuaire**, créez les groupes et préparez les invitations individuelles. Le lien d’activation est à usage unique et valable 48 heures. Le bouton de courriel ouvre un brouillon dans votre messagerie, où vous choisissez de l’envoyer. Le module **Demandes** fonctionne de la même manière pour les comptes actifs.
3. Dans **Droits d’accès**, choisissez un groupe ou une personne et les autorisations. La consultation et le téléchargement sont séparés. L’autorisation d’ajout s’applique aux dossiers. Une règle individuelle prime sur les règles de groupe au même niveau. Les droits de plusieurs groupes au même niveau s’additionnent. Une règle locale remplace les droits hérités. L’accès à tous les parents est requis. Une branche de premier niveau est privée jusqu’à l’attribution de ses droits.
4. Pour retirer un accès hérité, appliquez une règle individuelle sans case cochée. **Retirer cette règle** supprime uniquement la règle locale et peut donc rétablir les droits hérités. Pour révoquer toutes les sessions d’un collaborateur, suspendez son compte dans l’annuaire.
5. Importez les documents seuls ou une arborescence ZIP, avec ses dossiers vides. L’import ne remplace aucun élément existant. Un export de dossier inclut la branche entière seulement si le téléchargement est autorisé pour chacun de ses éléments. Limites de cette version par transfert ZIP : 32 Mio de contenu décompressé et 1 000 entrées, 63 niveaux de dossiers. Les documents déjà récupérés et les captures restent hors du contrôle du Hub.

Les PDF sont consultables page par page et les textes TXT/CSV ont un aperçu. Les fichiers Office peuvent être déposés et téléchargés selon les droits accordés.

## Lien sur le site académique EPS

Dans le site académique, créez une entrée **IA-IPR EPS** et utilisez
[`static/affichette-ia-ipr-eps.svg`](static/affichette-ia-ipr-eps.svg) comme visuel.
Liez l’image ou le bouton à l’adresse HTTPS du Hub suivie de `/connexion`.
Texte alternatif conseillé : **Accéder à l’espace IA-IPR EPS**.
Le Hub reste une application distincte reliée par ce lien. La page publique
du site académique ne contient aucun document privé ni identifiant.

En mode code, l’utilisateur saisit son adresse autorisée, reçoit un code individuel
à huit chiffres, puis dispose de 10 minutes pour le saisir. Chaque code est valable
une seule fois, avec cinq essais maximum. Les nouveaux membres activent d’abord leur
invitation. L’animateur gère ensuite les droits par groupe, personne et dossier.

## Installation sur un serveur

Prérequis : un serveur Linux autorisé par l’académie, Docker avec Compose, un nom de domaine pointant vers le serveur et les ports 80 et 443 disponibles. Le service Flask reste sur le réseau interne de Compose. Caddy reçoit les connexions HTTPS et gère le certificat. SQLite est conservé dans le volume `hub-data`, indépendamment des conteneurs.

Depuis la racine du dépôt sur le serveur, renseignez le domaine du Hub et le relais
SMTP autorisé à envoyer les codes. Le mode `email_code` est sélectionné par défaut
dans Compose. Le port 465 utilise SMTP sur TLS, les autres ports utilisent STARTTLS.
Si le relais requiert une authentification, ajoutez `HUB_SMTP_USER` et
`HUB_SMTP_PASSWORD` au fichier `.env` privé de l’hôte. Le lancement local sans
Compose conserve le mode mot de passe par défaut.

```bash
(umask 077 && cat > .env <<'CONFIG'
HUB_DOMAIN=hub-eps.exemple.fr
HUB_SMTP_HOST=smtp.exemple.fr
HUB_SMTP_PORT=587
HUB_SMTP_FROM=hub-eps@exemple.fr
CONFIG
)
install -d -m 700 secrets
# À faire une seule fois. Conservez cette clé entre les mises à jour.
if [ ! -e secrets/hub_key ]; then
  (umask 077 && openssl rand -hex 32 > secrets/hub_key)
  chmod 0444 secrets/hub_key
fi
docker compose build hub
docker compose run --rm hub flask --app app init-db --email animateur@exemple.fr
docker compose up -d
docker compose ps
```

La commande d’initialisation demande le mot de passe de l’animateur. Le dossier `secrets` est privé sur l’hôte. Le fichier de clé est lisible par l’utilisateur applicatif à travers le montage Compose. Vérifiez ensuite la réception d’un code sur le compte Animateur et l’accès via le
domaine HTTPS configuré. Pour une base existante, utilisez
`docker compose run --rm hub flask --app app migrate-db` à la place de
`init-db`, après une sauvegarde et avant le redémarrage. Si un reverse proxy académique existe déjà, utilisez sa configuration de publication à la place du service Caddy.

### Sauvegarder

```bash
backup="hub-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
docker compose exec -T hub flask --app app backup-db "/var/lib/ipr/$backup"
(umask 077 && docker compose cp "hub:/var/lib/ipr/$backup" "./$backup")
```

Conservez les copies dans un emplacement protégé et vérifiez la restauration sur une instance isolée. Une restauration se fait serveur arrêté, à partir d’une copie validée, en remplaçant la base et en écartant ses anciens fichiers WAL et SHM. La clé de session doit être sauvegardée séparément. Protégez les liens d’activation dans les journaux du reverse proxy.

### Périmètre de mise en service

Faites valider l’hébergement, l’authentification, les sauvegardes et les règles de conservation par l’académie avant l’import de documents réels. Derrière un proxy, le plafond de tentatives par IP est partagé tant que l’adresse cliente n’est pas transmise et reconnue via une chaîne de proxys de confiance.

Les invitations et demandes passent par la messagerie de l’animateur. La coédition Office doit être intégrée et testée sur une instance de l’éditeur validée par l’académie. Albert et les autres modules de RESANA restent à raccorder.
