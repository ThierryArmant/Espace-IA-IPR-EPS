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

## Avant une mise en service académique

Le site n’est pas déployé par ce dépôt. Pour une installation de recette, utilisez une instance HTTPS avec `HUB_PUBLIC_URL` fixé à l’origine publique exacte, `HUB_LOCAL_HTTP` désactivé, une clé de session privée et un chemin `HUB_DATABASE` placé sur un volume persistant privé. Prévoyez des sauvegardes restaurables de SQLite et évitez de consigner les chemins contenant des liens d’activation dans les journaux. Un seul serveur d’application utilise cette base locale. Faites valider l’hébergement, l’authentification, les sauvegardes et les règles de conservation par l’académie avant l’import de documents réels.

La coédition bureautique reste à intégrer et à tester sur une instance de l’éditeur institutionnel validée par l’académie. Les invitations et demandes passent actuellement par la messagerie de l’animateur. Albert et les autres modules de RESANA ne sont pas raccordés dans cette version.
