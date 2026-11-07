import hmac
import os
import re
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage

from flask import abort, current_app, flash, g, redirect, render_template, request, session, url_for

CODE_LIFETIME = 600
CODE_TRIES = 5
GENERIC_SENT = "Si cette adresse est autorisée, un code lui a été envoyé."


@dataclass(frozen=True)
class CodeMailer:
    host: str
    sender: str
    port: int
    username: str
    password: str

    @classmethod
    def from_environment(cls):
        host = os.environ.get("HUB_SMTP_HOST", "").strip()
        sender = os.environ.get("HUB_SMTP_FROM", "").strip()
        username = os.environ.get("HUB_SMTP_USER", "")
        password = os.environ.get("HUB_SMTP_PASSWORD", "")
        port = int(os.environ.get("HUB_SMTP_PORT", "587"))
        if not host or not re.fullmatch(r"[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+", sender):
            raise RuntimeError("Renseignez HUB_SMTP_HOST et HUB_SMTP_FROM pour la connexion par code.")
        if bool(username) != bool(password) or not 1 <= port <= 65535:
            raise RuntimeError("Vérifiez les paramètres d’authentification et le port SMTP.")
        return cls(host, sender, port, username, password)

    def send(self, address, code):
        mail = EmailMessage()
        mail["From"] = self.sender
        mail["To"] = address
        mail["Subject"] = "Votre code d’accès · IA-IPR EPS"
        mail.set_content(f"Votre code de connexion est {code}.\n\n"
                         "Il est valable 10 minutes et ne peut être utilisé qu’une fois.\n"
                         "Si vous n’avez pas demandé ce code, ignorez ce message.")
        context = ssl.create_default_context()
        transport = smtplib.SMTP_SSL if self.port == 465 else smtplib.SMTP
        options = {"context": context} if self.port == 465 else {}
        with transport(self.host, self.port, timeout=5, **options) as relay:
            if self.port != 465:
                relay.starttls(context=context)
            if self.username:
                relay.login(self.username, self.password)
            relay.send_message(mail)


def digest(purpose, value):
    key = current_app.secret_key.encode()
    return hmac.digest(key, f"{purpose}:{value}".encode(), "sha256").hex()


def request_code(mailer):
    email = request.form.get("email", "").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@,;?&#]+@[^\s@,;?&#]+\.[^\s@,;?&#]+", email):
        abort(400, "Adresse électronique invalide.")
    now = int(time.time())
    keys = (("code-email:" + digest("email", email), 4),
            ("code-ip:" + (request.remote_addr or "inconnue"), 60))
    g.db.execute("DELETE FROM attempts WHERE at < ?", (now - 900,))
    g.db.execute("DELETE FROM login_codes WHERE expires <= ? OR id = ?", (now, session.get("login_code")))
    for key, limit in keys:
        count = g.db.execute("SELECT COUNT(*) FROM attempts WHERE key=?", (key,)).fetchone()[0]
        if count >= limit:
            abort(429)
    g.db.executemany("INSERT INTO attempts VALUES(?,?)", [(key, now) for key, _ in keys])
    user = g.db.execute("SELECT id, session_version FROM users WHERE email=? AND active=1", (email,)).fetchone()
    challenge = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(10**8):08d}"
    g.db.execute("INSERT INTO login_codes VALUES(?,?,?,?,?,?)",
                 (challenge, user["id"] if user else None, user["session_version"] if user else None,
                  digest("code", challenge + code), now + CODE_LIFETIME, CODE_TRIES))
    g.db.commit()
    session["login_code"] = challenge
    if user:
        try:
            mailer.send(email, code)
        except (OSError, smtplib.SMTPException):
            # Do not log the exception itself: SMTP errors may contain addresses or message content.
            current_app.logger.warning("Échec d’envoi d’un code de connexion via le relais SMTP.")
    flash(GENERIC_SENT)
    return redirect(url_for("login"))


def verify_code():
    challenge = session.get("login_code", "")
    code = request.form.get("code", "").strip()
    row = g.db.execute(
        """SELECT login_codes.digest, login_codes.remaining, users.id AS user_id, users.session_version
           FROM login_codes LEFT JOIN users ON users.id=login_codes.user_id AND users.active=1
           AND users.session_version=login_codes.session_version
           WHERE login_codes.id=? AND login_codes.expires>?""",
        (challenge, int(time.time())),
    ).fetchone()
    if row and re.fullmatch(r"[0-9]{8}", code) and secrets.compare_digest(
        row["digest"], digest("code", challenge + code)
    ) and row["user_id"]:
        g.db.execute("DELETE FROM login_codes WHERE id=?", (challenge,))
        g.db.commit()
        return start_session(row["user_id"], row["session_version"])
    if row and row["remaining"] > 1:
        g.db.execute("UPDATE login_codes SET remaining=remaining-1 WHERE id=?", (challenge,))
        flash("Code incorrect. Vérifiez les huit chiffres reçus.")
    else:
        g.db.execute("DELETE FROM login_codes WHERE id=?", (challenge,))
        session.pop("login_code", None)
        flash("Code expiré ou nombre d’essais atteint. Demandez un nouveau code.")
    g.db.commit()
    return redirect(url_for("login"))


def start_session(user_id, version):
    session.clear()
    session["user"] = user_id
    session["version"] = version
    session.permanent = True
    return redirect(url_for("folder"))


def login_with_code(mailer):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "request-code":
            return request_code(mailer)
        if action == "verify-code":
            return verify_code()
        abort(400, "Action de connexion inconnue.")
    return render_template("login.html", use_code=True,
                           enter_code=bool(session.get("login_code")) and request.args.get("nouveau") != "1")
