"""Tableau des autorisations : personnes × dossiers principaux, à cocher.

Les membres du groupe « Gestion des autorisations » et l'animateur règlent ici,
pour chaque personne, l'accès aux dossiers de premier niveau :
  —           aucun accès individuel (la branche reste privée)
  Consulter   lire et télécharger
  Contribuer  lire, télécharger, déposer et créer des sous-dossiers
Chaque choix crée ou retire la règle individuelle correspondante.
"""
import re
import sqlite3
import unicodedata

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

MANAGERS_GROUP = "Gestion des autorisations"
EMAIL_DOMAIN = "ac-aix-marseille.fr"
EMAIL = re.compile(r"[^\s@,;?&#]+@[^\s@,;?&#]+\.[^\s@,;?&#]+")


SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS access_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL
);
"""


def upgrade_users(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if columns and "name" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN name TEXT")
    # Ordre d'affichage des dossiers (NULL : après les dossiers ordonnés, par date de création).
    columns = {row[1] for row in db.execute("PRAGMA table_info(nodes)")}
    if columns and "position" not in columns:
        db.execute("ALTER TABLE nodes ADD COLUMN position INTEGER")


def plain(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def surname_first(full_name):
    """« Prénom NOM » → « NOM Prénom » (le nom en majuscules passe devant)."""
    words = full_name.split()
    upper = [w.replace("-", "").replace("'", "").isupper() and len(w) > 1 for w in words]
    if words and not upper[0] and any(upper):
        first = upper.index(True)
        if all(upper[first:]):
            words = words[first:] + words[:first]
    return " ".join(words)


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


def register_authorizations(app, view, download, write, *, rights=None, find_node=None):
    bp = Blueprint("autorisations", __name__)
    levels = {"": 0, "consulter": view | download, "contribuer": view | download | write}

    def managers_group():
        row = g.db.execute("SELECT group_id FROM access_settings WHERE id=1 AND group_id IS NOT NULL").fetchone()
        if row is None:
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
        if g.get("db") is None:
            return {"can_manage_access": False}
        return {"can_manage_access": can_manage(), "managers_group_id": managers_group()}

    @bp.post("/autorisations/groupe-gestion")
    def choose_managers():
        if not g.user["admin"]:
            abort(403, "Ce réglage est réservé à l’animateur.")
        group = request.form.get("group", type=int)
        if group is not None and not g.db.execute("SELECT 1 FROM groups WHERE id=?", (group,)).fetchone():
            abort(400, "Groupe inconnu.")
        g.db.execute("INSERT INTO access_settings(id,group_id) VALUES(1,?) "
                     "ON CONFLICT(id) DO UPDATE SET group_id=excluded.group_id", (group,))
        g.db.commit()
        flash("Groupe qui gère les autorisations enregistré." if group else "Plus aucun groupe ne gère les autorisations (seuls les animateurs).")
        return redirect(url_for("directory"))

    def level(mask):
        if mask & write:
            return "contribuer"
        if mask & view:
            return "consulter"
        return ""

    def cell_value(mask, top):
        """Valeur affichée : "" = pas de règle (hérite du dossier au-dessus), "aucun" = accès retiré."""
        if mask is None:
            return ""
        return level(mask) or ("" if top else "aucun")

    @bp.route("/autorisations", methods=["GET", "POST"])
    def grid():
        if not can_manage():
            abort(403, "Ce tableau est réservé au groupe « Gestion des autorisations ».")
        parent_id = request.values.get("dossier", 1, type=int)
        parent = find_node(parent_id) if find_node else None
        if parent_id != 1 and (parent is None or parent["kind"] != "folder"):
            abort(404)
        top = parent_id == 1
        folders = g.db.execute(
            "SELECT id,name FROM nodes WHERE parent=? AND kind='folder' "
            "ORDER BY position IS NULL, position, id", (parent_id,)).fetchall()
        people = g.db.execute(
            "SELECT id,email,name,admin,active,password IS NOT NULL AS activated FROM users "
            "ORDER BY COALESCE(NULLIF(name,''), email) COLLATE NOCASE").fetchall()
        folder_ids = {row["id"] for row in folders}
        person_ids = {row["id"] for row in people}
        rules = {(row["node"], row["subject"]): row["mask"] for row in g.db.execute(
            "SELECT node,subject,mask FROM rules WHERE subject_kind='user'")}
        group_rows = g.db.execute("SELECT id,name FROM groups ORDER BY name COLLATE NOCASE").fetchall()
        group_ids = {row["id"] for row in group_rows}
        group_rules = {(row["node"], row["subject"]): row["mask"] for row in g.db.execute(
            "SELECT node,subject,mask FROM rules WHERE subject_kind='group'")}
        allowed_values = set(levels) | ({"aucun"} if not top else set())
        if request.method == "POST":
            changed = 0
            for key, value in request.form.items():
                match = re.fullmatch(r"acces-(g-)?(\d+)-(\d+)", key)
                if not match or value not in allowed_values:
                    continue
                kind = "group" if match[1] else "user"
                folder, subject = int(match[2]), int(match[3])
                if folder not in folder_ids or subject not in (group_ids if kind == "group" else person_ids):
                    abort(400)
                current = (group_rules if kind == "group" else rules).get((folder, subject))
                if cell_value(current, top) == value:
                    continue
                if value:
                    g.db.execute("""INSERT INTO rules VALUES(?, ?, ?, ?)
                                    ON CONFLICT(node,subject_kind,subject) DO UPDATE SET mask=excluded.mask""",
                                 (folder, kind, subject, levels.get(value, 0)))
                elif current is not None:
                    g.db.execute("DELETE FROM rules WHERE node=? AND subject_kind=? AND subject=?",
                                 (folder, kind, subject))
                else:
                    continue
                changed += 1
            g.db.commit()
            flash(f"{changed} autorisation(s) mise(s) à jour." if changed else "Aucun changement.")
            return redirect(url_for("autorisations.grid", dossier=parent_id) if not top
                            else url_for("autorisations.grid"))
        via_group = {(row["node"], row["user_id"]) for row in g.db.execute(
            """SELECT r.node, m.user_id FROM rules r JOIN memberships m
               ON r.subject_kind='group' AND r.subject=m.group_id WHERE r.mask & ? <> 0""", (view,))}
        cells = {(folder["id"], person["id"]): cell_value(rules.get((folder["id"], person["id"])), top)
                 for folder in folders for person in people}
        group_cells = {(folder["id"], group["id"]): cell_value(group_rules.get((folder["id"], group["id"])), top)
                       for folder in folders for group in group_rows}
        group_sizes = dict(g.db.execute("SELECT group_id, COUNT(*) FROM memberships GROUP BY group_id").fetchall())
        person_groups = {}
        for group, person in g.db.execute("SELECT group_id, user_id FROM memberships"):
            person_groups.setdefault(person, []).append(group)
        no_parent_access = set()
        trail = []
        if not top:
            no_parent_access = {person["id"] for person in people
                                if not rights(parent, person, structure=False) & view}
            node = parent
            while node is not None and node["parent"] is not None:
                trail.append(node)
                node = find_node(node["parent"])
            trail.reverse()
        has_children = {row[0] for row in g.db.execute(
            "SELECT DISTINCT parent FROM nodes WHERE kind='folder' AND parent IN (%s)"
            % ",".join("?" * len(folder_ids)), tuple(folder_ids))} if folder_ids else set()
        return render_template("autorisations.html", folders=folders, people=people, cells=cells,
                               via_group=via_group, managers_group=MANAGERS_GROUP,
                               has_group=managers_group() is not None, top=top, parent=parent,
                               trail=trail, no_parent_access=no_parent_access, has_children=has_children,
                               group_rows=group_rows, group_cells=group_cells, group_sizes=group_sizes,
                               person_groups=person_groups)

    @bp.route("/groupes", methods=["GET", "POST"])
    def groups_page():
        if not g.get("user"):
            abort(403)
        can_edit = can_manage()
        if request.method == "POST" and not can_edit:
            abort(403, "Seuls les animateurs peuvent modifier les groupes.")
        if request.method == "POST":
            if request.form.get("action") == "fiche":
                group = request.form.get("groupe", type=int)
                if g.db.execute("SELECT 1 FROM groups WHERE id=?", (group,)).fetchone() is None:
                    abort(400)
                known_people = {row[0] for row in g.db.execute("SELECT id FROM users")}
                wanted = {int(x) for x in request.form.getlist("membres") if x.isdigit()}
                if not wanted <= known_people:
                    abort(400)
                before = {row[0] for row in g.db.execute(
                    "SELECT user_id FROM memberships WHERE group_id=?", (group,))}
                for person in before - wanted:
                    g.db.execute("DELETE FROM memberships WHERE group_id=? AND user_id=?", (group, person))
                for person in wanted - before:
                    g.db.execute("INSERT INTO memberships(user_id,group_id) VALUES(?,?)", (person, group))
                tops = {row[0] for row in g.db.execute("SELECT id FROM nodes WHERE parent=1 AND kind='folder'")}
                access_changes = 0
                for key, value in request.form.items():
                    match = re.fullmatch(r"acces-(\d+)", key)
                    if not match or value not in levels:
                        continue
                    folder = int(match[1])
                    if folder not in tops:
                        abort(400)
                    row = g.db.execute("SELECT mask FROM rules WHERE node=? AND subject_kind='group' AND subject=?",
                                       (folder, group)).fetchone()
                    if cell_value(row[0] if row else None, True) == value:
                        continue
                    if value:
                        g.db.execute("""INSERT INTO rules VALUES(?, 'group', ?, ?)
                                        ON CONFLICT(node,subject_kind,subject) DO UPDATE SET mask=excluded.mask""",
                                     (folder, group, levels[value]))
                    else:
                        g.db.execute("DELETE FROM rules WHERE node=? AND subject_kind='group' AND subject=?",
                                     (folder, group))
                    access_changes += 1
                g.db.commit()
                members_changes = len(before ^ wanted)
                if members_changes or access_changes:
                    flash(f"Groupe enregistré : {members_changes} changement(s) de membres, "
                          f"{access_changes} changement(s) d’accès.")
                else:
                    flash("Aucun changement.")
                return redirect(url_for("autorisations.groups_page", ouvert=group) + f"#groupe-{group}")
            if request.form.get("action") == "creer":
                name = " ".join(request.form.get("name", "").split())
                if not 1 <= len(name) <= 80 or any(c in name for c in "/\\:"):
                    flash("Donnez un nom de groupe (80 caractères maximum, sans / \\ ni :).")
                else:
                    try:
                        g.db.execute("INSERT INTO groups(name) VALUES(?)", (name,))
                        new_id = g.db.execute("SELECT id FROM groups WHERE name=?", (name,)).fetchone()[0]
                        g.db.commit()
                        flash(f"Groupe « {name} » créé : cochez ses membres et choisissez ses dossiers, puis enregistrez.")
                        return redirect(url_for("autorisations.groups_page", ouvert=new_id) + f"#groupe-{new_id}")
                    except sqlite3.IntegrityError:
                        g.db.rollback()
                        flash("Ce nom de groupe existe déjà.")
                return redirect(url_for("autorisations.groups_page"))
            groups_shown = {int(x) for x in request.form.getlist("groupes") if x.isdigit()}
            known_groups = {row[0] for row in g.db.execute("SELECT id FROM groups")}
            known_people = {row[0] for row in g.db.execute("SELECT id FROM users")}
            if not groups_shown <= known_groups:
                abort(400)
            wanted = set()
            for key in request.form:
                match = re.fullmatch(r"m-(\d+)-(\d+)", key)
                if match:
                    group, person = int(match[1]), int(match[2])
                    if group not in groups_shown or person not in known_people:
                        abort(400)
                    wanted.add((group, person))
            before = {(row[0], row[1]) for row in g.db.execute("SELECT group_id,user_id FROM memberships")
                      if row[0] in groups_shown}
            for group, person in before - wanted:
                g.db.execute("DELETE FROM memberships WHERE group_id=? AND user_id=?", (group, person))
            for group, person in wanted - before:
                g.db.execute("INSERT INTO memberships(user_id,group_id) VALUES(?,?)", (person, group))
            g.db.commit()
            changes = len(before ^ wanted)
            flash(f"{changes} changement(s) enregistré(s) dans les groupes." if changes else "Aucun changement.")
            return redirect(url_for("autorisations.groups_page"))
        people = g.db.execute(
            "SELECT id,email,name,admin,active,password IS NOT NULL AS activated FROM users "
            "ORDER BY COALESCE(NULLIF(name,''), email) COLLATE NOCASE").fetchall()
        group_rows = g.db.execute("SELECT id,name FROM groups ORDER BY name COLLATE NOCASE").fetchall()
        members = {(row[0], row[1]) for row in g.db.execute("SELECT group_id,user_id FROM memberships")}
        sizes = dict(g.db.execute("SELECT group_id, COUNT(*) FROM memberships GROUP BY group_id").fetchall())
        tops = g.db.execute("SELECT id,name FROM nodes WHERE parent=1 AND kind='folder' "
                            "ORDER BY position IS NULL, position, id").fetchall() if can_edit else []
        group_access = {(row["node"], row["subject"]): cell_value(row["mask"], True) for row in g.db.execute(
            "SELECT node,subject,mask FROM rules WHERE subject_kind='group'")} if can_edit else {}
        return render_template("groupes.html", people=people, group_rows=group_rows, members=members, sizes=sizes,
                               can_edit=can_edit, tops=tops, group_access=group_access,
                               opened=request.args.get("ouvert", type=int),
                               members_of={row["id"]: {p for (gr, p) in members if gr == row["id"]} for row in group_rows})

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
            name = surname_first(name)
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
