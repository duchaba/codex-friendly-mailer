-- Friendly Mailer local database schema.
-- Dates are stored as ISO-8601 UTC text, for example 2026-10-03T19:30:00Z.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    email TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK (length(trim(email)) > 0 AND instr(email, '@') > 1),
    circle TEXT NOT NULL CHECK (length(trim(circle)) > 0),
    touch_date TEXT
        CHECK (touch_date IS NULL OR datetime(touch_date) IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_contacts_circle
    ON contacts (circle);

CREATE INDEX IF NOT EXISTS idx_contacts_touch_date
    ON contacts (touch_date);
