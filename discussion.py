"""Discussions instantanées entre membres connectés (à la manière d'une messagerie).

On clique sur une personne « En ligne » pour ouvrir une discussion ; on peut y
ajouter d'autres personnes. L'identité affichée est l'adresse mail du compte.
Les discussions sont éphémères : une discussion dont aucun participant n'a eu le
Hub ouvert depuis IDLE_SECONDS est effacée avec tous ses messages.
"""
import re
import sqlite3
import time

from flask import Blueprint, abort, g, jsonify, request

SCHEMA = """
DROP TABLE IF EXISTS chat;
DROP TABLE IF EXISTS chat_state;
CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS conversation_members(
    conversation_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    last_read INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(conversation_id, user_id)
);
CREATE TABLE IF NOT EXISTS conversation_messages(
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    user_id INTEGER,
    body TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS conversation_messages_conv ON conversation_messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS messagerie_presentee(user_id INTEGER PRIMARY KEY);
"""
IDLE_SECONDS = 10 * 60
ONLINE_SECONDS = 5 * 60
MAX_LENGTH = 1000
MAX_MEMBERS = 30


ACADEMIC_DOMAIN = "@ac-aix-marseille.fr"


def short_name(email):
    """prenom.nom@ac-aix-marseille.fr → « Prénom N. » ; autres adresses : inchangées."""
    if not email:
        return "—"
    if not email.lower().endswith(ACADEMIC_DOMAIN):
        return email
    local = email[: -len(ACADEMIC_DOMAIN)]
    first, _, last = local.partition(".")
    first = re.sub(r"\d+", "", first)
    last = re.sub(r"\d+", "", last)
    pretty = "-".join(part.capitalize() for part in first.split("-") if part)
    initial = last[:1].upper()
    if not pretty:
        return email
    return f"{pretty} {initial}." if initial else pretty


def register_discussion(app):
    bp = Blueprint("discussion", __name__)

    def now():
        return int(time.time())

    def cleanup():
        """Efface les discussions dont aucun participant n'est revenu depuis IDLE_SECONDS."""
        try:
            stale = [row[0] for row in g.db.execute(
                """SELECT c.id FROM conversations c WHERE c.created < :limit AND NOT EXISTS (
                       SELECT 1 FROM conversation_members m JOIN presence p ON p.user_id = m.user_id
                       WHERE m.conversation_id = c.id AND p.seen >= :limit)""",
                {"limit": now() - IDLE_SECONDS})]
            for conversation in stale:
                g.db.execute("DELETE FROM conversation_messages WHERE conversation_id=?", (conversation,))
                g.db.execute("DELETE FROM conversation_members WHERE conversation_id=?", (conversation,))
                g.db.execute("DELETE FROM conversations WHERE id=?", (conversation,))
            if stale:
                g.db.commit()
        except sqlite3.Error:
            g.db.rollback()

    def member_of(conversation_id):
        row = g.db.execute("SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
                           (conversation_id, g.user["id"])).fetchone()
        if row is None:
            abort(404)

    def members(conversation_id):
        return g.db.execute(
            """SELECT u.id, u.email, COALESCE(NULLIF(u.name,''), u.email) AS nom FROM conversation_members m
               JOIN users u ON u.id = m.user_id WHERE m.conversation_id=? ORDER BY u.email""",
            (conversation_id,)).fetchall()

    def title(conversation_id):
        others = [short_name(row["email"]) for row in members(conversation_id) if row["id"] != g.user["id"]]
        return ", ".join(others) if others else "Vous seul(e)"

    def online():
        return g.db.execute(
            """SELECT u.id, u.email, COALESCE(NULLIF(u.name,''), u.email) AS nom FROM presence p
               JOIN users u ON u.id = p.user_id
               WHERE u.active=1 AND p.seen >= ? AND u.id <> ? ORDER BY nom COLLATE NOCASE""",
            (now() - ONLINE_SECONDS, g.user["id"])).fetchall()

    def active_user(user_id):
        row = g.db.execute("SELECT id FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if row is None:
            abort(404)
        return row["id"]

    @bp.get("/discussions/etat")
    def state():
        cleanup()
        rows = g.db.execute(
            """SELECT m.conversation_id AS id,
                      (SELECT COUNT(*) FROM conversation_messages x WHERE x.conversation_id = m.conversation_id
                         AND x.id > m.last_read AND COALESCE(x.user_id, 0) <> :me) AS non_lus,
                      (SELECT MAX(id) FROM conversation_messages x WHERE x.conversation_id = m.conversation_id) AS dernier
               FROM conversation_members m WHERE m.user_id = :me ORDER BY dernier DESC""",
            {"me": g.user["id"]}).fetchall()
        introduced = g.db.execute("SELECT 1 FROM messagerie_presentee WHERE user_id=?",
                                  (g.user["id"],)).fetchone() is not None
        return jsonify(
            presentation=not introduced,
            conversations=[{"id": row["id"], "titre": title(row["id"]), "non_lus": row["non_lus"],
                            "dernier": row["dernier"] or 0,
                            "avec": [m["id"] for m in members(row["id"]) if m["id"] != g.user["id"]]}
                           for row in rows],
            en_ligne=[{"id": row["id"], "email": short_name(row["email"]), "nom": row["email"]} for row in online()])

    @bp.post("/discussions/presentation-vue")
    def introduced():
        g.db.execute("INSERT OR IGNORE INTO messagerie_presentee(user_id) VALUES(?)", (g.user["id"],))
        g.db.commit()
        return jsonify(ok=True)

    @bp.post("/discussions/nouvelle")
    def start():
        other = active_user(request.form.get("avec", type=int))
        if other == g.user["id"]:
            abort(400, "Choisissez une autre personne.")
        # Reprendre la discussion à deux existante plutôt que d'en créer une seconde.
        row = g.db.execute(
            """SELECT a.conversation_id FROM conversation_members a
               JOIN conversation_members b ON b.conversation_id = a.conversation_id AND b.user_id = ?
               WHERE a.user_id = ? AND (SELECT COUNT(*) FROM conversation_members c
                                       WHERE c.conversation_id = a.conversation_id) = 2""",
            (other, g.user["id"])).fetchone()
        if row:
            return jsonify(id=row[0])
        cursor = g.db.execute("INSERT INTO conversations(created) VALUES(?)", (now(),))
        conversation = cursor.lastrowid
        g.db.executemany("INSERT INTO conversation_members(conversation_id, user_id) VALUES(?, ?)",
                         [(conversation, g.user["id"]), (conversation, other)])
        g.db.commit()
        return jsonify(id=conversation)

    @bp.get("/discussions/<int:conversation_id>")
    def read(conversation_id):
        member_of(conversation_id)
        after = request.args.get("apres", 0, type=int)
        rows = g.db.execute(
            """SELECT x.id, x.user_id, x.body, x.created, u.email FROM conversation_messages x
               LEFT JOIN users u ON u.id = x.user_id
               WHERE x.conversation_id=? AND x.id > ? ORDER BY x.id LIMIT 200""",
            (conversation_id, after)).fetchall()
        last = max([after] + [row["id"] for row in rows])
        if rows:
            try:
                g.db.execute("UPDATE conversation_members SET last_read=MAX(last_read, ?) "
                             "WHERE conversation_id=? AND user_id=?", (last, conversation_id, g.user["id"]))
                g.db.commit()
            except sqlite3.Error:
                g.db.rollback()
        return jsonify(
            titre=title(conversation_id),
            membres=[{"id": row["id"], "email": row["email"], "nom": short_name(row["email"])} for row in members(conversation_id)],
            messages=[{"id": row["id"], "auteur": short_name(row["email"]), "texte": row["body"],
                       "heure": time.strftime("%H:%M", time.localtime(row["created"])),
                       "moi": row["user_id"] == g.user["id"],
                       "systeme": row["user_id"] is None} for row in rows])

    @bp.post("/discussions/<int:conversation_id>/envoyer")
    def send(conversation_id):
        member_of(conversation_id)
        body = request.form.get("texte", "").strip()
        if not body:
            abort(400, "Message vide.")
        if len(body) > MAX_LENGTH:
            abort(400, f"Message trop long ({MAX_LENGTH} caractères au plus).")
        g.db.execute("INSERT INTO conversation_messages(conversation_id, user_id, body, created) VALUES(?,?,?,?)",
                     (conversation_id, g.user["id"], body, now()))
        g.db.commit()
        return jsonify(ok=True)

    @bp.post("/discussions/<int:conversation_id>/ajouter")
    def add(conversation_id):
        member_of(conversation_id)
        other = active_user(request.form.get("avec", type=int))
        count = g.db.execute("SELECT COUNT(*) FROM conversation_members WHERE conversation_id=?",
                             (conversation_id,)).fetchone()[0]
        if count >= MAX_MEMBERS:
            abort(400, "Discussion complète.")
        added = g.db.execute("INSERT OR IGNORE INTO conversation_members(conversation_id, user_id) VALUES(?, ?)",
                             (conversation_id, other)).rowcount
        if added:
            email = g.db.execute("SELECT email FROM users WHERE id=?", (other,)).fetchone()[0]
            g.db.execute("INSERT INTO conversation_messages(conversation_id, user_id, body, created) VALUES(?,?,?,?)",
                         (conversation_id, None, f"{short_name(g.user['email'])} a ajouté {short_name(email)}", now()))
        g.db.commit()
        return jsonify(ok=True)

    @bp.post("/discussions/<int:conversation_id>/quitter")
    def leave(conversation_id):
        member_of(conversation_id)
        g.db.execute("DELETE FROM conversation_members WHERE conversation_id=? AND user_id=?",
                     (conversation_id, g.user["id"]))
        left = g.db.execute("SELECT COUNT(*) FROM conversation_members WHERE conversation_id=?",
                            (conversation_id,)).fetchone()[0]
        if left == 0:
            g.db.execute("DELETE FROM conversation_messages WHERE conversation_id=?", (conversation_id,))
            g.db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        else:
            g.db.execute("INSERT INTO conversation_messages(conversation_id, user_id, body, created) VALUES(?,?,?,?)",
                         (conversation_id, None, f"{short_name(g.user['email'])} a quitté la discussion", now()))
        g.db.commit()
        return jsonify(ok=True)

    app.register_blueprint(bp)
