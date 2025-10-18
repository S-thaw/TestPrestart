-- schema.sql
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS records;

CREATE TABLE users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password_hash TEXT,
    role TEXT
);

CREATE TABLE records(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_no TEXT,
    name TEXT,
    date_text TEXT,
    date_iso TEXT,
    comments TEXT,
    damage TEXT,
    file_path TEXT,
    created_by TEXT,
    created_at_iso TEXT
);

-- default admin
INSERT INTO users(username,password_hash,role)
VALUES ('admin','$pbkdf2:sha256:260000$demoHash$example', 'admin');
