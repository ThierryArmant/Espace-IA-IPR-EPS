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

### Stocker les fichiers dans Nuage (compte fonctionnel)

Les collègues travaillent uniquement dans le Hub. Le Hub conserve l’arborescence,
les droits et les échanges. Le contenu des fichiers déposés est rangé dans Nuage,
dans `IA IPR EPS/Stockage Hub`, sous un nom unique. Renommer ou déplacer un dossier
dans le Hub ne touche donc pas à Nuage. Aucun collègue n’a besoin d’un compte Nuage
pour consulter ou télécharger un fichier, et seul le Hub décide qui y a accès.

1. Créez ou obtenez un compte Nuage fonctionnel (et non personnel), puis
   connectez-vous-y dans le navigateur.
2. Sur le serveur, lancez `flask --app app nuage-autoriser --fichier secrets/nuage_password`
   et ouvrez le lien affiché. La commande affiche `HUB_NUAGE_LOGIN` et enregistre
   le mot de passe d’application dans le fichier privé indiqué.
3. Ajoutez à la configuration privée du serveur (variables d’environnement du site
   chez l’hébergeur, ou fichier `.env` avec Compose) :
   `HUB_NUAGE_LOGIN`, puis `HUB_NUAGE_APP_PASSWORD_FILE` (chemin du fichier) ou
   `HUB_NUAGE_APP_PASSWORD`. `HUB_NUAGE_ROOT` indique le dossier de départ dans Nuage, sous-dossiers compris, par exemple `Dossiers IPR EPS/IA IPR EPS` (par défaut `IA IPR EPS`). Il vaut aussi pour les documents créés en coédition.
4. Redémarrez, puis vérifiez avec `flask --app app nuage-verifier`.
5. Pour déplacer dans Nuage les fichiers déjà déposés dans la base du Hub :
   faites une sauvegarde, puis lancez `flask --app app nuage-transferer`.

Sans ces variables, le Hub garde le fonctionnement précédent (fichiers dans SQLite).
Le mot de passe d’application ouvre tout le compte fonctionnel : ne le placez jamais
dans le dépôt, et révoquez-le dans les paramètres de sécurité de Nuage en cas de doute.
Si Nuage ne répond pas, les dépôts sont refusés sans rien enregistrer, et les
téléchargements affichent un message d’indisponibilité.
La création de documents en coédition (`.odt`/`.ods`) continue d’utiliser le compte
Nuage personnel de chaque collègue, car l’éditeur s’ouvre dans Nuage.

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


## Espace documentaire GitHub Pages et Jalios

La page `espace-documentaire.html` affiche l’arborescence et le lien vers le dossier Nuage.
Le navigateur ouvre les documents dans Nuage, qui applique les droits d’accès.
Les scripts Jalios conservés dans `static/` sont une base pour un éventuel dépôt intégré.
Ils nécessitent un service configuré dans `static/jalios-config.js` et ne sont pas chargés sur cette page.
Le contrat ci-dessous est celui du raccordement attendu, et non celui de l’API
Jalios native. Il doit être mis en œuvre ou adapté côté académique avant activation.

- **GET** sur l’URL du service, avec `folder` facultatif. Sans paramètre, le service
  utilise la racine IA-IPR EPS. Réponse JSON
  `{"folder":{"id":"…","name":"…"},"folders":[{"id":"…","name":"…"}],"files":[{"name":"…","url":"…"}],"canUpload":true,"csrfToken":"…"}`.
  Jalios doit filtrer les dossiers et fichiers selon le compte académique connecté.
  Les liens sont des URL protégées sur le site pédagogique.
- **POST** sur la même URL avec `folder`, un formulaire multipart (champ `file`) et
  l’en-tête `X-CSRF-Token`. Le service contrôle le compte, la destination autorisée,
  le type et la taille du fichier, ainsi que le jeton CSRF avant l’enregistrement.
  Il répond `{"uploaded":true}` uniquement après la création du document dans Jalios.
- Le service doit répondre `401` sans session et `403` pour un accès refusé.
  Il doit autoriser l’origine `https://thierryarmant.github.io` si la connexion
  académique est compatible avec cet accès depuis le navigateur. Vérifier aussi
  la transmission de la session intersite et les règles de déploiement académique.
  Aucune clé API partagée ni aucun identifiant académique ne doit être publié.

Recette attendue : depuis l’interface GitHub, déposer un PDF fictif, vérifier sa
présence dans le dossier Jalios choisi, puis tester la consultation et le dépôt
avec un compte autorisé et un compte qui ne l’est pas.

### Essai local avec Nuage sur Windows

Téléchargez le ZIP du dépôt, extrayez-le puis double-cliquez sur
`Lancer-test-Nuage.cmd` dans le dossier qui contient `nuage_pilote.py`.
Python 3.12 est requis. Le lanceur ouvre un serveur uniquement sur
`127.0.0.1:8088` et la page locale dans votre navigateur. Si le navigateur ne
s’ouvre pas, utilisez l’adresse affichée dans la fenêtre du lanceur.

Cliquez sur **Connecter mon compte Nuage**, ouvrez le lien proposé et autorisez
le pilote sur le site officiel. Revenez dans l’onglet local et cliquez sur
**J’ai autorisé le pilote**. Le sélecteur PDF devient alors disponible.

Le pilote attend un dossier **IA IPR EPS** à la racine du compte
`nuage01.apps.education.fr`. Au premier dépôt il crée le sous-dossier
**Pilote Hub**, puis y enregistre uniquement des PDF de test de 10 Mio maximum,
sous des noms générés sans écraser les fichiers existants. Vous pouvez vérifier
leur présence puis les télécharger depuis l’interface locale.

Le flux Nuage fournit un mot de passe d’application lié au compte. Le pilote
le garde en mémoire locale et limite lui-même ses requêtes au sous-dossier de
test. Le mot de passe d’application n’est pas limité à ce sous-dossier par
Nuage. Après le test, fermez le pilote et révoquez son autorisation depuis les
paramètres de sécurité de Nuage. Cette recette ne met aucun service en ligne et
n’active pas le dépôt sur GitHub Pages.
