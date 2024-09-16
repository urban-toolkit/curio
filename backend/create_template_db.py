import sqlite3

conn = sqlite3.connect('template.db')

cursor = conn.cursor()

command = """
CREATE TABLE template (
    id TEXT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    type VARCHAR(50) NOT NULL,
    description TEXT,
    accessLevel VARCHAR(50) NOT NULL,
    code TEXT NOT NULL,
    custom BOOLEAN NOT NULL
);
"""

cursor.execute(command)

command_projeto = """
CREATE TABLE projeto (
    id TEXT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    dependency TEXT,
    boxType VARCHAR(50) NOT NULL
);
"""
cursor.execute(command_projeto)

conn.commit()

conn.close()
