import os
import sqlite3
import pytz
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "appointments.db"
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Bucharest")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

PROGRAM = {
    0: ("08:00", "19:00"),
    1: ("08:00", "19:00"),
    2: ("08:00", "19:00"),
    3: ("08:00", "19:00"),
    4: ("08:00", "19:00"),
    5: ("09:00", "14:00"),
    6: None
}

def _get_calendar_service():
    import base64, json
    b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
    if b64:
        data = json.loads(base64.b64decode(b64).decode())
        creds = service_account.Credentials.from_service_account_info(data, scopes=SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)

def _get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS appointments
                 (id INTEGER PRIMARY KEY, name TEXT, service TEXT,
                  date TEXT, time TEXT, duration INTEGER, phone TEXT)""")
    conn.commit()
    return conn

def get_available_slots(date_str, duration=60):
    try:
        service = _get_calendar_service()
        day_start = f"{date_str}T00:00:00+03:00"
        day_end = f"{date_str}T23:59:59+03:00"
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=day_start,
            timeMax=day_end,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        occupied = []
        for event in events:
            start = event["start"].get("dateTime", "")
            end = event["end"].get("dateTime", "")
            if start:
                occupied.append({"start": start[11:16], "end": end[11:16]})
        return occupied
    except Exception as e:
        print(f"[Calendar] Eroare get_slots: {e}")
        return []

def is_slot_available(date_str, time_str, duration):
    try:
        occupied = get_available_slots(date_str, duration)
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration)
        for slot in occupied:
            slot_start = datetime.strptime(f"{date_str} {slot['start']}", "%Y-%m-%d %H:%M")
            slot_end = datetime.strptime(f"{date_str} {slot['end']}", "%Y-%m-%d %H:%M")
            if not (end_dt <= slot_start or start_dt >= slot_end):
                return False
        return True
    except Exception as e:
        print(f"[Calendar] Eroare verificare slot: {e}")
        return True

def get_free_slots(date_str, duration=30):
    try:
        tz = pytz.timezone("Europe/Bucharest")
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        program = PROGRAM.get(dt.weekday())
        if not program:
            return []
        occupied = get_available_slots(date_str, duration)
        start_p = datetime.strptime(f"{date_str} {program[0]}", "%Y-%m-%d %H:%M")
        end_p = datetime.strptime(f"{date_str} {program[1]}", "%Y-%m-%d %H:%M")
        now = datetime.now(tz).replace(tzinfo=None)
        current = start_p
        if date_str == datetime.now(tz).strftime("%Y-%m-%d"):
            if now.minute < 30:
                rounded = now.replace(minute=30, second=0, microsecond=0)
            else:
                rounded = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            current = max(start_p, rounded)
        free = []
        while current + timedelta(minutes=duration) <= end_p:
            end_slot = current + timedelta(minutes=duration)
            busy = False
            for slot in occupied:
                s = datetime.strptime(f"{date_str} {slot['start']}", "%Y-%m-%d %H:%M")
                e = datetime.strptime(f"{date_str} {slot['end']}", "%Y-%m-%d %H:%M")
                if not (end_slot <= s or current >= e):
                    busy = True
                    break
            if not busy:
                free.append(current.strftime("%H:%M"))
            current += timedelta(minutes=30)
        return free
    except Exception as e:
        print(f"[Calendar] Eroare free_slots: {e}")
        return []

def book_appointment(name, service, date, time, duration=60, phone=""):
    if duration not in (30, 45, 60):
        duration = 60
    dt = datetime.strptime(date, "%Y-%m-%d")
    program = PROGRAM.get(dt.weekday())
    if not program:
        return False
    start_p = datetime.strptime(f"{date} {program[0]}", "%Y-%m-%d %H:%M")
    end_p = datetime.strptime(f"{date} {program[1]}", "%Y-%m-%d %H:%M")
    start_a = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    end_a = start_a + timedelta(minutes=duration)
    if start_a < start_p or end_a > end_p:
        return False
    if not is_slot_available(date, time, duration):
        return False
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO appointments (name, service, date, time, duration, phone) VALUES (?, ?, ?, ?, ?, ?)",
            (name, service, date, time, duration, phone)
        )
        conn.commit()
        conn.close()
        cal_service = _get_calendar_service()
        start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration)
        event = {
            "summary": f"{service} - {name}",
            "description": f"Programare: {service}\nPacient: {name}\nDurată: {duration} min",
            "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": TIMEZONE},
        }
        created = cal_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        print(f"[Calendar] Programare creata: {created.get('htmlLink')}")
        return True
    except Exception as e:
        print(f"[Calendar] Eroare: {e}")
        return False

def cancel_appointment(name, date, time):
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT phone FROM appointments WHERE name=? AND date=? AND time=?",
            (name, date, time)
        ).fetchone()
        phone = row[0] if row else ""
        conn.execute("DELETE FROM appointments WHERE name=? AND date=? AND time=?", (name, date, time))
        conn.commit()
        conn.close()
        cal = _get_calendar_service()
        events = cal.events().list(
            calendarId=CALENDAR_ID,
            timeMin=f"{date}T00:00:00+03:00",
            timeMax=f"{date}T23:59:59+03:00",
            q=name,
            singleEvents=True
        ).execute().get("items", [])
        for event in events:
            if time in event["start"].get("dateTime", ""):
                cal.events().delete(calendarId=CALENDAR_ID, eventId=event["id"]).execute()
                break
        return phone
    except Exception as e:
        print(f"[Calendar] Eroare anulare: {e}")
        return ""

def reschedule_appointment(name, old_date, old_time, new_date, new_time, duration=60):
    try:
        if not is_slot_available(new_date, new_time, duration):
            return False, "ocupat"
        cancel_appointment(name, old_date, old_time)
        conn = _get_conn()
        phone_row = conn.execute(
            "SELECT phone FROM appointments WHERE name=? ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        phone = phone_row[0] if phone_row else ""
        conn.close()
        success = book_appointment(name, "Reprogramare", new_date, new_time, duration, phone)
        return (True, phone) if success else (False, "eroare")
    except Exception as e:
        print(f"[Calendar] Eroare reprogramare: {e}")
        return False, "eroare"
