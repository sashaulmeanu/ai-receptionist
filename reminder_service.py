import sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sms_service import send_reminder

DB_FILE = "appointments.db"

def check_and_send_reminders():
    try:
        maine = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            "SELECT name, service, date, time, phone FROM appointments WHERE date = ? AND phone != ''",
            (maine,)
        ).fetchall()
        conn.close()
        for name, service, date, time, phone in rows:
            tel = phone if phone.startswith("+") else "+4" + phone
            send_reminder(tel, name, service, date, time)
            print(f"[Reminder] Trimis la {tel} pentru {date} {time}")
    except Exception as e:
        print(f"[Reminder] Eroare: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_send_reminders,
        'cron',
        hour=10,
        minute=0,
        id='daily_reminders'
    )
    scheduler.add_job(
        send_raport_zilnic,
        'cron',
        hour=8,
        minute=0,
        id='daily_report'
    )
    scheduler.start()
    print("[Reminder] Scheduler pornit — rulează zilnic la 10:00")
    return scheduler

def send_raport_zilnic():
    """Trimite SMS cu programarile din ziua curenta la 08:00."""
    try:
        from twilio.rest import Client
        import os
        azi = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            "SELECT name, service, time, duration FROM appointments WHERE date=? ORDER BY time",
            (azi,)
        ).fetchall()
        conn.close()
        
        admin_phone = os.getenv("ADMIN_PHONE_NUMBER")
        if not admin_phone:
            print("[Raport] ADMIN_PHONE_NUMBER lipseste din .env")
            return
            
        if not rows:
            msg = f"Raport {azi}: Nu sunt programari azi."
        else:
            linii = [f"Raport programari {azi}:"]
            for name, service, time, duration in rows:
                linii.append(f"- {time} {name} ({service}, {duration}min)")
            msg = "\n".join(linii)
        
        client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        client.messages.create(
            body=msg,
            from_=os.getenv("TWILIO_PHONE_NUMBER"),
            to=admin_phone
        )
        print(f"[Raport] Trimis la {admin_phone}")
    except Exception as e:
        print(f"[Raport] Eroare: {e}")
