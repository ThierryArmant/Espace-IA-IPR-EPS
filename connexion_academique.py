"""Se connecter avec son compte académique (connexion officielle d'apps.education).

Le Hub utilise le flux de connexion de Nuage : la personne s'identifie sur la page
officielle avec ses identifiants académiques et autorise l'accès. Le Hub lit alors
son adresse électronique, révoque aussitôt l'accès accordé, et ouvre la session si
l'adresse figure dans la liste des membres. Un compte en attente est activé à cette
occasion : plus besoin de lien d'invitation personnel ni de mot de passe.
"""
import base64
import hmac
import json
import re
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, flash, g, jsonify, redirect, render_template, session, url_for

from login_code import start_session
from nuage_pilote import NUAGE_LOGIN, check_flow_url, nuage_request

FLOW_LIFETIME = 900
SERVER = re.compile(r"nuage[0-9]*\.apps\.education\.fr")
ERRORS = (ValueError, KeyError, TypeError, OSError, URLError)


def _basic(login, password):
    return "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode("ascii")


def academic_email(server, login, password):
    """Adresse du compte, puis révocation immédiate du mot de passe d'application."""
    headers = {"Authorization": _basic(login, password), "OCS-APIRequest": "true",
               "Accept": "application/json"}
    email = None
    try:
        status, body = nuage_request(f"{server}/ocs/v2.php/cloud/user?format=json", "GET",
                                     headers=headers, limit=256 * 1024)
        if status == 200:
            email = (json.loads(body).get("ocs", {}).get("data", {}).get("email") or "").strip().lower()
    finally:
        try:
            nuage_request(f"{server}/ocs/v2.php/core/apppassword", "DELETE", headers=headers)
        except ERRORS:
            pass
    if not email and "@" in login:
        email = login.strip().lower()
    return email or None


def register_academic_login(app, login_url=NUAGE_LOGIN):
    bp = Blueprint("academique", __name__)
    secret = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
    cipher = Fernet(base64.urlsafe_b64encode(hmac.digest(secret, b"ia-ipr-academique-v1", "sha256")))

    def flow():
        try:
            return json.loads(cipher.decrypt(session.get("academique", ""), ttl=FLOW_LIFETIME))
        except (InvalidToken, ValueError, TypeError):
            return None

    @bp.post("/connexion/academique")
    def start():
        session.pop("academique", None)
        try:
            status, body = nuage_request(f"{login_url}/index.php/login/v2", "POST", payload=b"",
                                         headers={"User-Agent": "Espace IA-IPR EPS"})
            if status != 200:
                raise ValueError("indisponible")
            data = json.loads(body)
            link = check_flow_url(data["login"], "flow")
            poll = check_flow_url(data["poll"]["endpoint"], "poll")
            token = data["poll"]["token"]
            if not isinstance(token, str) or not 1 <= len(token) <= 512:
                raise ValueError("suivi invalide")
        except ERRORS:
            flash("La connexion académique est momentanément indisponible. Réessayez dans quelques minutes.")
            return redirect(url_for("login"))
        session["academique"] = cipher.encrypt(json.dumps([link, poll, token]).encode()).decode("ascii")
        return redirect(url_for("academique.waiting"))

    @bp.get("/connexion/academique")
    def waiting():
        current = flow()
        if current is None:
            return redirect(url_for("login"))
        return render_template("connexion_academique.html", link=current[0])

    @bp.post("/connexion/academique/verifier")
    def check():
        current = flow()
        if current is None:
            return jsonify(state="expired", message="La demande a expiré. Recommencez.")
        _, poll, token = current
        try:
            status, body = nuage_request(poll, "POST", payload=urlencode({"token": token}).encode(),
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        except ERRORS:
            return jsonify(state="waiting")
        if status != 200:
            return jsonify(state="waiting")
        session.pop("academique", None)
        try:
            data = json.loads(body)
            server = urlsplit(data["server"])
            login, password = data["loginName"], data["appPassword"]
            if server.scheme != "https" or not SERVER.fullmatch(server.netloc or ""):
                raise ValueError("serveur inconnu")
            email = academic_email(f"https://{server.netloc}", login, password)
        except ERRORS:
            return jsonify(state="error", message="Votre compte académique n’a pas pu être vérifié.")
        if not email:
            return jsonify(state="error", message="Votre adresse académique n’a pas pu être lue.")
        user = g.db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user is None:
            return jsonify(state="refused", message=f"L’adresse {email} ne figure pas parmi les membres de "
                                                    "l’espace. Contactez l’animateur.")
        if not user["active"] and user["password"] is not None:
            return jsonify(state="refused", message="Ce compte est suspendu. Contactez l’animateur.")
        if user["password"] is None:
            g.db.execute("UPDATE users SET password='academique', active=1 WHERE id=?", (user["id"],))
            g.db.execute("DELETE FROM invites WHERE user_id=?", (user["id"],))
        g.db.commit()
        user = g.db.execute("SELECT id, session_version FROM users WHERE id=?", (user["id"],)).fetchone()
        start_session(user["id"], user["session_version"])
        return jsonify(state="ok", next=url_for("folder"))

    app.register_blueprint(bp)
