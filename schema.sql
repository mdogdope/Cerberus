--
-- File generated with SQLiteStudio v3.4.17 on Mon Mar 16 17:26:21 2026
--
-- Text encoding used: UTF-8
--
PRAGMA foreign_keys = off;
BEGIN TRANSACTION;

-- Table: children
CREATE TABLE IF NOT EXISTS children (child_id INTEGER PRIMARY KEY ASC AUTOINCREMENT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL);

-- Table: devices
CREATE TABLE IF NOT EXISTS devices (device_id INTEGER PRIMARY KEY ASC AUTOINCREMENT UNIQUE NOT NULL, device_name TEXT NOT NULL UNIQUE, device_ip TEXT NOT NULL UNIQUE, child TEXT REFERENCES children (child_id), settings TEXT CHECK (json_valid(settings)));

-- Table: event_types
CREATE TABLE IF NOT EXISTS event_types (event_type_id INTEGER PRIMARY KEY ASC AUTOINCREMENT NOT NULL UNIQUE, name TEXT UNIQUE NOT NULL);
INSERT INTO event_types (event_type_id, name) VALUES (0, 'image');
INSERT INTO event_types (event_type_id, name) VALUES (1, 'text');
INSERT INTO event_types (event_type_id, name) VALUES (2, 'audio');

-- Table: events
CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY ASC AUTOINCREMENT UNIQUE NOT NULL, device INTEGER REFERENCES devices (device_id) NOT NULL, report TEXT CHECK (json_valid(report)) NOT NULL, full_image_path TEXT, cell_image_path TEXT, sound_path TEXT, event_type INTEGER REFERENCES event_types (event_type_id));

-- Table: sessions
CREATE TABLE IF NOT EXISTS sessions (session_id INTEGER PRIMARY KEY ASC AUTOINCREMENT UNIQUE NOT NULL, user_id INTEGER REFERENCES users (user_id) NOT NULL, token TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL CHECK (datetime(expires_at) IS NOT NULL));

-- Table: settings
CREATE TABLE IF NOT EXISTS settings (setting_id INTEGER PRIMARY KEY ASC AUTOINCREMENT UNIQUE NOT NULL, discord_webhook TEXT, profile TEXT);

-- Table: users
CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY ASC AUTOINCREMENT UNIQUE NOT NULL, display_name TEXT NOT NULL, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL);

COMMIT TRANSACTION;
PRAGMA foreign_keys = on;
