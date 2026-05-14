from fastapi import FastAPI, Form, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from anthropic import Anthropic
from dotenv import load_dotenv
from calendar_service import book_appointment, get_available_slots, get_free_slots, cancel_appointment, reschedule_appointment
from sms_service import send_confirmare, send_anulare, send_confirmare as send_reprogramare
from datetime import date, datetime
import pytz
import json, re, os

from reminder_service import start_scheduler
from reminder_service import start_scheduler
load_dotenv()
app = FastAPI()
scheduler = start_scheduler()
scheduler = start_scheduler()
claude = Anthropic()
conversations = {}

ZILE_RO = {"Monday":"Luni","Tuesday":"Marți","Wednesday":"Miercuri","Thursday":"Joi","Friday":"Vineri","Saturday":"Sâmbătă","Sunday":"Duminică"}
LUNI_RO = {"January":"ianuarie","February":"februarie","March":"martie","April":"aprilie","May":"mai","June":"iunie","July":"iulie","August":"august","September":"septembrie","October":"octombrie","November":"noiembrie","December":"decembrie"}


_slots_cache = {"data": "", "timestamp": 0}

def _get_cached_slots():
    import time
    from datetime import timedelta
    from calendar_service import get_free_slots
    if time.time() - _slots_cache["timestamp"] < 300:
        return _slots_cache["data"]
    zile_libere = ""
    for i in range(14):
        ziua = (datetime.now(pytz.timezone("Europe/Bucharest")).date() + timedelta(days=i)).strftime("%Y-%m-%d")
        sloturi = get_free_slots(ziua, 30)
        if sloturi:
            zile_libere += f"\n{ziua}: {', '.join(sloturi[:6])}"
    _slots_cache["data"] = zile_libere
    _slots_cache["timestamp"] = time.time()
    return zile_libere

def get_system_prompt():
    azi = datetime.now(pytz.timezone("Europe/Bucharest")).date()
    zi = ZILE_RO[azi.strftime("%A")]
    luna = LUNI_RO[azi.strftime("%B")]
    data_azi = f"{zi}, {azi.day} {luna} {azi.year}"
    data_iso = azi.strftime("%Y-%m-%d")
    ora = datetime.now(pytz.timezone("Europe/Bucharest")).hour
    ora_zi = "dimineața" if ora < 12 else "după-amiaza" if ora < 18 else "seara"
    
    from datetime import timedelta
    from calendar_service import get_free_slots
    zile_libere = _get_cached_slots()
    
    return f"""Ești Andreea, asistenta Clinicii Stomatologice Zâmbet Frumos din București.

CARACTER: Caldă, directă, profesională. Vorbești ca un om, nu ca un robot.
- Folosești: "sigur", "imediat verific", "o secundă", "bineînțeles"
- NU folosești: "voi procesa", "cu siguranță", "desigur", fraze lungi
- MAX 2 propoziții per răspuns. Niciodată liste rostite.
- Salut după oră: Bună {ora_zi}!

DATA AZI: {data_azi} ({data_iso})

Propune DOAR ore din lista de mai sus. Dacă ora e ocupată, oferă imediat 2-3 alternative din aceeași zi sau ziua următoare.

PROGRAM: Luni-Vineri 08:00-19:00, Sâmbătă 09:00-14:00, Duminică închis
SERVICII: Detartraj 45min/250RON, Consultație 30min/150RON, Plombă 60min/300-500RON, Albire 60min/800RON, Extracție 45min/200-400RON, Urgență 30min

COLECTEAZĂ în ordine, câte unul pe rând:
1. Numele complet
2. Telefon (07XXXXXXXX)
3. Serviciul dorit
4. Data și ora preferată (doar din sloturi disponibile)
5. Durata: 30, 45 sau 60 min

URGENȚE: empatie scurtă + slot azi imediat.

Când ai TOATE datele:
BOOK_APPOINTMENT:{{"name":"Ion Popescu","service":"Detartraj","date":"2026-05-07","time":"10:00","duration":45,"phone":"0712345678"}}

Reprogramare:
RESCHEDULE_APPOINTMENT:{{"name":"Ion Popescu","old_date":"2026-05-07","old_time":"10:00","new_date":"2026-05-08","new_time":"11:00","duration":30}}

Anulare:
CANCEL_APPOINTMENT:{{"name":"Ion Popescu","service":"Detartraj","date":"2026-05-07","time":"10:00"}}

Transfer uman: TRANSFER_TO_HUMAN
Nu te prezenta din nou după primul mesaj."""

@app.post("/incoming-call")
async def incoming_call():
    response = VoiceResponse()
    gather = Gather(input="speech", action="/handle-speech", timeout=3, speech_timeout="auto", language="ro-RO")
    gather.say("Clinica Zâmbet Frumos, Sofia. Cu ce vă pot ajuta?", voice="Polly.Carmen")
    response.append(gather)
    response.say("Vă rugăm sunați din nou. Mulțumim!", voice="Polly.Carmen")
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-speech")
async def handle_speech(CallSid: str = Form(...), SpeechResult: str = Form(default="")):
    response = VoiceResponse()

    if not SpeechResult.strip():
        gather = Gather(input="speech", action="/handle-speech", timeout=3, speech_timeout="auto", language="ro-RO")
        gather.say("Nu v-am auzit. Puteți repeta?", voice="Polly.Carmen")
        response.append(gather)
        return Response(content=str(response), media_type="application/xml")

    if CallSid not in conversations:
        conversations[CallSid] = []
    conversations[CallSid].append({"role": "user", "content": SpeechResult})

    ai_response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=get_system_prompt(),
        messages=conversations[CallSid]
    )
    reply = ai_response.content[0].text

    # Transfer uman
    if "TRANSFER_TO_HUMAN" in reply:
        spoken = reply.replace("TRANSFER_TO_HUMAN", "").strip()
        response.say(spoken or "Vă transfer acum.", voice="Polly.Carmen")
        response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
        _cleanup(CallSid)
        return Response(content=str(response), media_type="application/xml")

    # Reprogramare
    if "RESCHEDULE_APPOINTMENT:" in reply:
        spoken_part, res_json = reply.split("RESCHEDULE_APPOINTMENT:", 1)
        spoken_part = spoken_part.strip()
        try:
            json_match = re.search(r'\{[^}]+\}', res_json, re.DOTALL)
            res = json.loads(json_match.group() if json_match else res_json.strip())
            duration = int(res.get("duration", 60))
            success, phone = reschedule_appointment(
                res["name"], res["old_date"], res["old_time"],
                res["new_date"], res["new_time"], duration
            )
            if success:
                msg = f"Reprogramarea a fost făcută! Noua programare: {res['new_date']} la ora {res['new_time']}."
                response.say((spoken_part + " " + msg).strip(), voice="Polly.Carmen")
                if phone:
                    tel = phone if phone.startswith("+") else "+4" + phone
                    send_reprogramare(tel, res["name"], "Reprogramare", res["new_date"], res["new_time"], duration)
            elif phone == "ocupat":
                free = get_free_slots(res["new_date"], duration)
                optiuni = ", ".join(free[:4]) if free else "nicio oră liberă"
                msg = f"Ora {res['new_time']} e ocupată pe {res['new_date']}. Ore disponibile: {optiuni}."
                response.say(msg, voice="Polly.Carmen")
                conversations[CallSid].append({"role": "assistant", "content": msg})
                gather = Gather(input="speech", action="/handle-speech", timeout=6, speech_timeout="auto", language="ro-RO")
                gather.say(msg, voice="Polly.Carmen")
                response.append(gather)
                return Response(content=str(response), media_type="application/xml")
            else:
                response.say("A apărut o problemă cu reprogramarea. Vă transfer.", voice="Polly.Carmen")
                response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
            _cleanup(CallSid)
        except Exception as e:
            print(f"[Eroare reprogramare] {e}")
            response.say("Problemă la reprogramare. Vă transfer.", voice="Polly.Carmen")
            response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
            _cleanup(CallSid)
        return Response(content=str(response), media_type="application/xml")

    # Anulare
    if "CANCEL_APPOINTMENT:" in reply:
        spoken_part, cancel_json = reply.split("CANCEL_APPOINTMENT:", 1)
        spoken_part = spoken_part.strip()
        try:
            import re as re2
            json_match = re2.search(r'\{[^}]+\}', cancel_json, re2.DOTALL)
            cancel = json.loads(json_match.group() if json_match else cancel_json.strip())
            phone = cancel_appointment(cancel["name"], cancel["date"], cancel["time"])
            msg = f"Programarea pentru {cancel.get('service','consultație')} din {cancel['date']} la ora {cancel['time']} a fost anulată."
            response.say((spoken_part + " " + msg).strip(), voice="Polly.Carmen")
            response.say("O zi bună!", voice="Polly.Carmen")
            if phone:
                tel = phone if phone.startswith("+") else "+4" + phone
                send_anulare(tel, cancel["name"], cancel.get("service","consultație"), cancel["date"], cancel["time"])
            _cleanup(CallSid)
        except Exception as e:
            print(f"[Eroare anulare] {e}")
            response.say("A apărut o problemă. Vă transfer la echipă.", voice="Polly.Carmen")
            response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
            _cleanup(CallSid)
        return Response(content=str(response), media_type="application/xml")

    # Programare
    if "BOOK_APPOINTMENT:" in reply:
        spoken_part, booking_json = reply.split("BOOK_APPOINTMENT:", 1)
        spoken_part = spoken_part.strip()
        try:
            json_match = re.search(r'\{[^}]+\}', booking_json, re.DOTALL)
            booking = json.loads(json_match.group() if json_match else booking_json.strip())
            duration = int(booking.get("duration", 60))
            if duration not in (30, 45, 60):
                duration = 60
            phone = booking.get("phone", "")

            success = book_appointment(
                name=booking["name"],
                service=booking.get("service", "Consultație"),
                date=booking["date"],
                time=booking["time"],
                duration=duration,
                phone=phone
            )

            if success:
                confirmare = f"Excelent! Programare confirmată: {booking.get('service')} pe {booking['date']} la {booking['time']}, {duration} minute."
                response.say((spoken_part + " " + confirmare).strip(), voice="Polly.Carmen")
                response.say("O zi bună!", voice="Polly.Carmen")
                if phone:
                    tel = phone if phone.startswith("+") else "+4" + phone
                    send_confirmare(tel, booking["name"], booking.get("service","consultație"), booking["date"], booking["time"], duration)
                _cleanup(CallSid)
            else:
                free = get_free_slots(booking['date'], duration)
                if free:
                    optiuni = ", ".join(free[:4])
                    msg = f"Ora {booking['time']} este ocupată. Ore disponibile pe {booking['date']}: {optiuni}. Ce preferați?"
                else:
                    msg = f"Ziua de {booking['date']} este complet ocupată. Doriți altă zi?"
                conversations[CallSid].append({"role": "assistant", "content": msg})
                gather = Gather(input="speech", action="/handle-speech", timeout=6, speech_timeout="auto", language="ro-RO")
                gather.say(msg, voice="Polly.Carmen")
                response.append(gather)

        except Exception as e:
            print(f"[Eroare booking] {e}")
            response.say("A apărut o problemă. Vă transfer la echipă.", voice="Polly.Carmen")
            response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
            _cleanup(CallSid)

        return Response(content=str(response), media_type="application/xml")

    # Conversatie normala
    conversations[CallSid].append({"role": "assistant", "content": reply})
    gather = Gather(input="speech", action="/handle-speech", timeout=4, speech_timeout="auto", language="ro-RO")
    gather.say(reply, voice="Polly.Carmen")
    response.append(gather)
    response.say("Vă mulțumim. O zi bună!", voice="Polly.Carmen")
    return Response(content=str(response), media_type="application/xml")

@app.post("/call-ended")
async def call_ended(CallSid: str = Form(...)):
    _cleanup(CallSid)
    return {"status": "ok"}

def _cleanup(call_sid: str):
    conversations.pop(call_sid, None)
