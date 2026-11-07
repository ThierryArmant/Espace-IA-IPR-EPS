PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password TEXT,
    admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 0,
    session_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER REFERENCES users(id),
    group_id INTEGER REFERENCES groups(id),
    PRIMARY KEY (user_id,group_id)
);
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    parent INTEGER REFERENCES nodes(id),
    name TEXT NOT NULL COLLATE NOCASE,
    kind TEXT NOT NULL CHECK(kind IN ('folder','file')),
    color TEXT NOT NULL,
    content BLOB,
    updated TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now')),
    UNIQUE(parent,name)
);
CREATE TABLE IF NOT EXISTS rules (
    node INTEGER REFERENCES nodes(id),
    subject_kind TEXT CHECK(subject_kind IN ('user','group')),
    subject INTEGER NOT NULL,
    mask INTEGER NOT NULL CHECK(mask BETWEEN 0 AND 7),
    PRIMARY KEY (node,subject_kind,subject)
);
CREATE TABLE IF NOT EXISTS invites (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key);
INSERT OR IGNORE INTO nodes(id,parent,name,kind,color) VALUES(1,NULL,'Espace IA-IPR EPS','folder','bleu');
CREATE TABLE IF NOT EXISTS login_codes (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    session_version INTEGER,
    digest TEXT NOT NULL,
    expires INTEGER NOT NULL,
    remaining INTEGER NOT NULL CHECK(remaining > 0)
);
CREATE INDEX IF NOT EXISTS login_codes_expires ON login_codes(expires);

CREATE TABLE IF NOT EXISTS node_id_watermark (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    last_deleted_id INTEGER NOT NULL
);
INSERT OR IGNORE INTO node_id_watermark(singleton,last_deleted_id) VALUES(1,0);
