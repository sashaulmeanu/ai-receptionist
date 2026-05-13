import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

def _client():
    return Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

FROM = os.getenv("TWILIO_PHONE_NUMBER")

def send_confirmare(phone, name, service, date, time, duration):
    try:
        _client().messages.create(
            body=f"Buna ziua, {name}! Programarea la Clinica Zambet Frumos a fost confirmata: {service}, {date} ora {time} ({duration} min). Va asteptam! Anulare: +40215550100",
            from_=FROM, to=phone
        )
        print(f"[SMS] Confirmare → {phone}")
        return True
    except Exception as e:
        print(f"[SMS] Eroare: {e}")
        return False

def send_reminder(phone, name, service, date, time):
    try:
        _client().messages.create(
            body=f"Reminder Clinica Zambet Frumos: Maine {date} la {time} aveti {service}. Va asteptam! Anulare: +40215550100",
            from_=FROM, to=phone
        )
        print(f"[SMS] Reminder → {phone}")
        return True
    except Exception as e:
        print(f"[SMS] Eroare: {e}")
        return False

def send_anulare(phone, name, service, date, time):
    try:
        _client().messages.create(
            body=f"Buna ziua, {name}! Programarea ({service}, {date} ora {time}) a fost anulata. Reprogramare: +40215550100",
            from_=FROM, to=phone
        )
        print(f"[SMS] Anulare → {phone}")
        return True
    except Exception as e:
        print(f"[SMS] Eroare: {e}")
        return False
