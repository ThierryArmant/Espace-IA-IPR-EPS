CREATE TABLE IF NOT EXISTS ipr_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    group_id INTEGER NOT NULL REFERENCES groups(id)
);
CREATE TABLE IF NOT EXISTS ipr_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    module TEXT NOT NULL CHECK(module IN ('evenements','reunions','creneaux','questionnaires','marque-pages','publications')),
    author_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL DEFAULT '',
    ends_at TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    capacity INTEGER,
    questions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now'))
);
CREATE INDEX IF NOT EXISTS ipr_entries_scope ON ipr_entries(group_id,module);
CREATE TABLE IF NOT EXISTS ipr_responses (
    entry_id INTEGER NOT NULL REFERENCES ipr_entries(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    value TEXT NOT NULL,
    PRIMARY KEY (entry_id,user_id)
);

CREATE TABLE IF NOT EXISTS document_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    sender_id INTEGER NOT NULL REFERENCES users(id),
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    nuage_file TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M','now'))
);
CREATE TABLE IF NOT EXISTS document_notification_recipients (
    notification_id INTEGER NOT NULL REFERENCES document_notifications(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
    PRIMARY KEY (user_id,notification_id)
);
