"""Grist (tableurs) et Docs (textes) comme outils de l'espace.

On crée le tableur dans Grist ou le document dans Docs, puis on range son lien
dans un dossier du Hub. Le lien n'est visible que des personnes autorisées sur
ce dossier. Les partages dans Grist ou Docs se règlent dans ces outils.
"""
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, g, redirect, request, url_for

TOOLS = {
    "grist": ("Grist", "https://grist.numerique.gouv.fr/", {"grist.numerique.gouv.fr"}),
    "docs": ("Docs", "https://docs.numerique.gouv.fr/", {"docs.numerique.gouv.fr"}),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS folder_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('grist','docs')),
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    author_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now'))
);
CREATE INDEX IF NOT EXISTS folder_links_node ON folder_links(node_id);
"""


def tool_of(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or len(url) > 2048:
        return None
    for kind, (_, _, hosts) in TOOLS.items():
        if parts.hostname in hosts:
            return kind
    return None


def register_tools(app, allowed, rights, view, write):
    bp = Blueprint("outils", __name__)

    def content(node):
        return rights(node, structure=False) if node["parent"] is not None else 0

    def links(node):
        if not content(node) & view:
            return []
        return g.db.execute("SELECT * FROM folder_links WHERE node_id=? ORDER BY title COLLATE NOCASE",
                            (node["id"],)).fetchall()

    @bp.app_context_processor
    def values():
        return {"tools": TOOLS, "folder_links": links}

    @bp.post("/dossier/<int:node_id>/liens")
    def add(node_id):
        node = allowed(node_id, view, "folder")
        if not content(node) & write:
            abort(404)
        url = request.form.get("url", "").strip()
        title = request.form.get("title", "").strip()
        kind = tool_of(url)
        if kind is None:
            flash("Collez un lien commençant par https://grist.numerique.gouv.fr/ ou https://docs.numerique.gouv.fr/.")
        elif not 1 <= len(title) <= 180:
            flash("Donnez un titre de 180 caractères maximum.")
        else:
            g.db.execute("INSERT INTO folder_links(node_id,kind,title,url,author_id) VALUES(?,?,?,?,?)",
                         (node_id, kind, title, url, g.user["id"]))
            g.db.commit()
            flash(f"« {title} » a été ajouté au dossier.")
        return redirect(url_for("folder", node_id=node_id))

    @bp.post("/dossier/<int:node_id>/liens/<int:link_id>/retirer")
    def remove(node_id, link_id):
        node = allowed(node_id, view, "folder")
        if not content(node) & write:
            abort(404)
        g.db.execute("DELETE FROM folder_links WHERE id=? AND node_id=?", (link_id, node_id))
        g.db.commit()
        flash("Lien retiré du dossier. Le tableur ou le document existe toujours dans son outil.")
        return redirect(url_for("folder", node_id=node_id))

    app.register_blueprint(bp)
