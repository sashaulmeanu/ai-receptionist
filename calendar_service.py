import sqlite3
from datetime import datetime, timedelta

DB_FILE = "appointments.db"

def _get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS appointments
                 (id INTEGER PRIMARY KEY, name TEXT, service TEXT,
                  date TEXT, time TEXT, duration INTEGER)""")
    conn.commit()
    return conn

def get_available_slots(date, duration=60):
    return []

def book_appointment(name, service, date, time, duration=60):
    if duration not in (30, 45, 60):
        duration = 60
    try:
        conn = _get_conn()
        conn.execute("INSERT INTO appointments (name, service, date, time, duration) VALUES (?, ?, ?, ?, ?)",
                     (name, service, date, time, duration))
        conn.commit()
        conn.close()
        print("[DB] Programare salvata: " + name + " pe " + date + " la " + time)
        return True
    except Exception as e:
        print("[DB] Eroare: " + str(e))
        return False
