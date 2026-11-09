"""Nouveautés automatiques : dépôts, créations, liens et modifications de documents.

Chaque événement est rattaché à un dossier. Une personne voit les nouveautés des
dossiers dont elle peut lire le contenu, sauf ses propres actions : tous les
membres d'un groupe ayant accès au dossier les reçoivent donc en même temps.
Les modifications faites dans Nuage (Collabora) sont repérées quand un dossier
est affiché ; les enregistrements successifs d'un même document sont regroupés.
"""
import sqlite3

from flask import Blueprint, g, render_template, url_for

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now'))
);
CREATE INDEX IF NOT EXISTS activity_node ON activity(node_id);
CREATE TABLE IF NOT EXISTS activity_seen (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nuage_file_state (
    folder_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    modified TEXT,
    PRIMARY KEY (folder_id, name)
);
CREATE TABLE IF NOT EXISTS nuage_folder_seen (
    folder_id INTEGER PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE
);
"""
LABELS = {
    "depot": ("📄", "déposé"),
    "creation": ("✚", "créé"),
    "lien": ("🔗", "ajouté (lien)"),
    "ajout": ("📄", "ajouté dans Nuage"),
    "modification": ("✎", "modifié"),
    "import": ("🗂", "importé (dossier complet)"),
}
RECENT = 300


def record(db, node_id, kind, name, actor_id=None, *, fresh=False):
    """Enregistre une nouveauté (le commit reste à la charge de l'appelant).

    fresh=True : fichier tout juste écrit par le Hub ; sa date Nuage sera reprise
    à l'affichage suivant sans créer de « modification ».
    """
    db.execute("INSERT INTO activity(node_id,kind,name,actor_id) VALUES(?,?,?,?)",
               (node_id, kind, name, actor_id))
    if fresh:
        db.execute("INSERT INTO nuage_file_state(folder_id,name,modified) VALUES(?,?,NULL) "
                   "ON CONFLICT(folder_id,name) DO UPDATE SET modified=NULL", (node_id, name))


def detect_changes(db, folder_id, files):
    """Compare la liste Nuage d'un dossier avec l'état connu et note les changements."""
    try:
        first_time = db.execute("SELECT 1 FROM nuage_folder_seen WHERE folder_id=?", (folder_id,)).fetchone() is None
        known = dict(db.execute("SELECT name, modified FROM nuage_file_state WHERE folder_id=?", (folder_id,)))
        changed = False
        for item in files:
            name, modified = item["name"], item["modified"]
            if name not in known:
                if not first_time:
                    db.execute("INSERT INTO activity(node_id,kind,name) VALUES(?,?,?)", (folder_id, "ajout", name))
                db.execute("INSERT INTO nuage_file_state VALUES(?,?,?)", (folder_id, name, modified))
                changed = True
            elif known[name] != modified:
                if known[name] is not None:
                    # Regrouper les enregistrements d'une même séance (2 heures).
                    db.execute("""DELETE FROM activity WHERE node_id=? AND name=? AND kind='modification'
                                  AND created_at >= strftime('%Y-%m-%d %H:%M','now','-2 hours')""",
                               (folder_id, name))
                    db.execute("INSERT INTO activity(node_id,kind,name) VALUES(?,?,?)",
                               (folder_id, "modification", name))
                db.execute("UPDATE nuage_file_state SET modified=? WHERE folder_id=? AND name=?",
                           (modified, folder_id, name))
                changed = True
        if first_time:
            db.execute("INSERT OR IGNORE INTO nuage_folder_seen VALUES(?)", (folder_id,))
            changed = True
        if changed:
            db.commit()
    except sqlite3.Error:
        db.rollback()


def register_activity(app, rights, find_node, view):
    bp = Blueprint("activite", __name__)

    def visible_entries(limit=RECENT):
        rows = g.db.execute(
            """SELECT a.*, u.name AS actor_name, u.email AS actor_email FROM activity a
               LEFT JOIN users u ON u.id=a.actor_id
               WHERE a.actor_id IS NULL OR a.actor_id<>? ORDER BY a.id DESC LIMIT ?""",
            (g.user["id"], limit))
        entries = []
        for row in rows:
            node = find_node(row["node_id"])
            if node is not None and rights(node, structure=False) & view:
                entries.append((row, node))
        return entries

    def last_seen():
        row = g.db.execute("SELECT last_id FROM activity_seen WHERE user_id=?", (g.user["id"],)).fetchone()
        return row[0] if row else 0

    @bp.app_context_processor
    def counter():
        if not g.get("user") or g.get("db") is None:
            return {}
        seen = last_seen()
        unread = sum(1 for row, _ in visible_entries(100) if row["id"] > seen)
        return {"nouveautes_non_lues": unread}

    @bp.get("/nouveautes")
    def page():
        seen = last_seen()
        entries = visible_entries()
        if entries and entries[0][0]["id"] > seen:
            g.db.execute("INSERT INTO activity_seen VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_id=excluded.last_id",
                         (g.user["id"], entries[0][0]["id"]))
            g.db.commit()
        return render_template("nouveautes.html", entries=entries, seen=seen, labels=LABELS)

    app.register_blueprint(bp)
