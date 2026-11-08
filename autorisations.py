"""Tableau des autorisations : personnes × dossiers principaux, à cocher.

Les membres du groupe « Gestion des autorisations » et l'animateur règlent ici,
pour chaque personne, l'accès aux dossiers de premier niveau :
  —           aucun accès individuel (la branche reste privée)
  Consulter   lire et télécharger
  Contribuer  lire, télécharger, déposer et créer des sous-dossiers
Chaque choix crée ou retire la règle individuelle correspondante.
"""
import re
import unicodedata

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

MANAGERS_GROUP = "Gestion des autorisations"
EMAIL_DOMAIN = "ac-aix-marseille.fr"
EMAIL = re.compile(r"[^\s@,;?&#]+@[^\s@,;?&#]+\.[^\s@,;?&#]+")


def upgrade_users(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if columns and "name" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN name TEXT")


def plain(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def guess_email(full_name):
    """« NOM Prénom » → prenom.nom@ac-aix-marseille.fr (à vérifier)."""
    words = full_name.split()
    last = [w for w in words if w.replace("-", "").replace("'", "").isupper()]
    first = [w for w in words if w not in last]
    if not last or not first or not all(any(c.islower() for c in w) for w in first):
        return None
    local = "-".join(first) + "." + "-".join(last)
    local = re.sub(r"[^a-z0-9.\-]", "", plain(local).lower())
    return f"{local}@{EMAIL_DOMAIN}"


def register_authorizations(app, view, download, write):
    bp = Blueprint("autorisations", __name__)
    levels = {"": 0, "consulter": view | download, "contribuer": view | download | write}

    def managers_group():
        row = g.db.execute("SELECT id FROM groups WHERE name=?", (MANAGERS_GROUP,)).fetchone()
        return row[0] if row else None

    def can_manage():
        if not g.get("user"):
            return False
        if g.user["admin"]:
            return True
        group = managers_group()
        return group is not None and g.db.execute(
            "SELECT 1 FROM memberships WHERE group_id=? AND user_id=?", (group, g.user["id"])).fetchone() is not None

    @bp.app_context_processor
    def controls():
        return {"can_manage_access": can_manage() if g.get("db") is not None else False}

    def level(mask):
        if mask & write:
            return "contribuer"
        if mask & view:
            return "consulter"
        return ""

    @bp.route("/autorisations", methods=["GET", "POST"])
    def grid():
        if not can_manage():
            abort(403, "Ce tableau est réservé au groupe « Gestion des autorisations ».")
        folders = g.db.execute(
            "SELECT id,name FROM nodes WHERE parent=1 AND kind='folder' ORDER BY id").fetchall()
        people = g.db.execute(
            "SELECT id,email,name,active,password IS NOT NULL AS activated FROM users "
            "ORDER BY COALESCE(NULLIF(name,''), email) COLLATE NOCASE").fetchall()
        folder_ids = {row["id"] for row in folders}
        person_ids = {row["id"] for row in people}
        rules = {(row["node"], row["subject"]): row["mask"] for row in g.db.execute(
            "SELECT node,subject,mask FROM rules WHERE subject_kind='user'")}
        if request.method == "POST":
            changed = 0
            for key, value in request.form.items():
                match = re.fullmatch(r"acces-(\d+)-(\d+)", key)
                if not match or value not in levels:
                    continue
                folder, person = int(match[1]), int(match[2])
                if folder not in folder_ids or person not in person_ids:
                    abort(400)
                current = rules.get((folder, person))
                if level(current or 0) == value and (current is not None or value):
                    continue
                if value:
                    g.db.execute("""INSERT INTO rules VALUES(?, 'user', ?, ?)
                                    ON CONFLICT(node,subject_kind,subject) DO UPDATE SET mask=excluded.mask""",
                                 (folder, person, levels[value]))
                elif current is not None:
                    g.db.execute("DELETE FROM rules WHERE node=? AND subject_kind='user' AND subject=?",
                                 (folder, person))
                else:
                    continue
                changed += 1
            g.db.commit()
            flash(f"{changed} autorisation(s) mise(s) à jour." if changed else "Aucun changement.")
            return redirect(url_for("autorisations.grid"))
        via_group = {(row["node"], row["user_id"]) for row in g.db.execute(
            """SELECT r.node, m.user_id FROM rules r JOIN memberships m
               ON r.subject_kind='group' AND r.subject=m.group_id WHERE r.mask & ? <> 0""", (view,))}
        cells = {(folder["id"], person["id"]): level(rules.get((folder["id"], person["id"]), 0))
                 for folder in folders for person in people}
        return render_template("autorisations.html", folders=folders, people=people, cells=cells,
                               via_group=via_group, managers_group=MANAGERS_GROUP,
                               has_group=managers_group() is not None)

    @bp.post("/autorisations/personnes")
    def add_people():
        if not g.user["admin"]:
            abort(403, "L’ajout de personnes est réservé à l’animateur.")
        created, errors = 0, []
        for line in request.form.get("people", "").splitlines()[:500]:
            line = line.strip()
            if not line:
                continue
            name, _, email = (part.strip() for part in line.partition(";"))
            email = (email or guess_email(name) or "").lower()
            if not name or len(name) > 120 or len(email) > 254 or not EMAIL.fullmatch(email):
                errors.append(line)
                continue
            existing = g.db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                g.db.execute("UPDATE users SET name=? WHERE id=?", (name, existing[0]))
            else:
                g.db.execute("INSERT INTO users(email,name) VALUES(?,?)", (email, name))
                created += 1
        g.db.commit()
        flash(f"{created} personne(s) ajoutée(s). Envoyez-leur ensuite l’invitation depuis l’annuaire."
              + (f" Lignes non reconnues : {' | '.join(errors[:5])}" if errors else ""))
        return redirect(url_for("autorisations.grid"))

    app.register_blueprint(bp)
