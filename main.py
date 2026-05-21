from fastapi import FastAPI, Form, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from anthropic import Anthropic
from dotenv import load_dotenv
from calendar_service import (
    book_appointment,
    get_available_slots,
    get_free_slots,
    cancel_appointment,
    reschedule_appointment,
)
from sms_service import send_confirmare, send_anulare
from datetime import date
import json
import re
import os
import logging

from reminder_service import start_scheduler

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("sofia")

# === Setup ===
load_dotenv()
app = FastAPI()
scheduler = start_scheduler()
claude = Anthropic()
conversations = {}

ZILE_RO = {
    "Monday": "Luni", "Tuesday": "Marți", "Wednesday": "Miercuri",
    "Thursday": "Joi", "Friday": "Vineri", "Saturday": "Sâmbătă",
    "Sunday": "Duminică",
}
LUNI_RO = {
    "January": "ianuarie", "February": "februarie", "March": "martie",
    "April": "aprilie", "May": "mai", "June": "iunie", "July": "iulie",
    "August": "august", "September": "septembrie", "October": "octombrie",
    "November": "noiembrie", "December": "decembrie",
}

SERVICE_DURATIONS = {
    "detartraj": 45,
    "consultatie": 30, "consultație": 30,
    "plomba": 60, "plombă": 60,
    "albire": 60,
    "extractie": 45, "extracție": 45,
    "urgenta": 30, "urgență": 30,
}


def infer_duration(service: str) -> int:
    s = (service or "").lower().strip()
    for key, dur in SERVICE_DURATIONS.items():
        if key in s:
            return dur
    return 30


def get_system_prompt():
    azi = date.today()
    zi = ZILE_RO[azi.strftime("%A")]
    luna = LUNI_RO[azi.strftime("%B")]
    data_azi = f"{zi}, {azi.day} {luna} {azi.year}"
    data_iso = azi.strftime("%Y-%m-%d")
    return f"""Ești Sofia, recepționista AI a Clinicii Stomatologice Zâmbet Frumos din București.
VORBEȘTI DOAR ÎN ROMÂNĂ. MAX 1-2 propoziții scurte. Fii directă, nu repeta informații.
DATA DE AZI: {data_azi} ({data_iso})

REGULĂ DE FORMATARE: NU folosi asteriscuri, bold, markdown sau emoji în răspunsuri. Doar text simplu, conversațional. Răspunsurile tale sunt citite cu voce tare de TTS.

PROGRAM: Luni-Vineri 08:00-19:00, Sâmbătă 09:00-14:00, Duminică închis

SERVICII (durata este FIXĂ - NU întreba clientul despre durată):
- Detartraj: 45min, 250 RON
- Consultație: 30min, 150 RON
- Plombă: 60min, 300-500 RON
- Albire: 60min, 800 RON
- Extracție: 45min, 200-400 RON
- Urgență: 30min

FLUX - colectează DOAR aceste 4 informații, în ordine:
1. Numele complet
2. Numărul de telefon (07XXXXXXXX)
3. Serviciul dorit
4. Data și ora preferată

REGULA CRITICĂ: NU întreba clientul despre durată. Durata o știi tu din lista de servicii.

Imediat ce ai cele 4 informații, termină răspunsul cu această linie:
BOOK_APPOINTMENT:{{"name":"Ion Popescu","service":"Detartraj","date":"2026-05-18","time":"10:00","phone":"0712345678"}}

URGENȚE: empatie + slot în aceeași zi.

Reprogramare:
RESCHEDULE_APPOINTMENT:{{"name":"Ion Popescu","old_date":"2026-05-07","old_time":"10:00","new_date":"2026-05-08","new_time":"11:00"}}

Anulare:
CANCEL_APPOINTMENT:{{"name":"Ion Popescu","service":"Detartraj","date":"2026-05-07","time":"10:00"}}

Transfer uman: TRANSFER_TO_HUMAN
Nu te prezenta din nou după primul mesaj. Nu spune Desigur sau Cu siguranță."""


# === Helpers TwiML ===

def _twiml_gather(text: str, timeout: int = 5) -> Response:
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/handle-speech",
        timeout=timeout,
        speech_timeout="auto",
        language="ro-RO",
    )
    gather.say(text, voice="Google.ro-RO-Wavenet-A")
    response.append(gather)
    response.say("Vă rugăm sunați din nou. Mulțumim!", voice="Google.ro-RO-Wavenet-A")
    return Response(content=str(response), media_type="application/xml")


def _twiml_say_hangup(text: str) -> Response:
    response = VoiceResponse()
    response.say(text, voice="Google.ro-RO-Wavenet-A")
    response.hangup()
    return Response(content=str(response), media_type="application/xml")


def _twiml_transfer(text: str) -> Response:
    response = VoiceResponse()
    if text:
        response.say(text, voice="Google.ro-RO-Wavenet-A")
    response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
    return Response(content=str(response), media_type="application/xml")


def _strip_formatting(text: str) -> str:
    """Curăță asteriscuri și markdown din text înainte de TTS."""
    if not text:
        return text
    text = re.sub(r"[*_]+", "", text)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"#+\s*", "", text)
    return text.strip()


def _extract_json(text: str):
    text = text.replace("\n", " ")
    match = re.search(r"\{[^{}]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        log.warning(f"JSON decode error: {e} | raw: {match.group()!r}")
        return None


def _format_phone(phone: str) -> str:
    if not phone:
        return ""
    return phone if phone.startswith("+") else "+4" + phone


# === Routes ===

@app.post("/incoming-call")
async def incoming_call():
    log.info("Apel nou primit")
    return _twiml_gather("Clinica Zâmbet Frumos, Sofia. Cu ce vă pot ajuta?")


@app.post("/handle-speech")
async def handle_speech(CallSid: str = Form(...), SpeechResult: str = Form(default="")):
    log.info(f"[{CallSid}] USER: {SpeechResult!r}")

    if not SpeechResult.strip():
        return _twiml_gather("Nu v-am auzit. Puteți repeta?")

    if CallSid not in conversations:
        conversations[CallSid] = []
    conversations[CallSid].append({"role": "user", "content": SpeechResult})

    try:
        ai_response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=get_system_prompt(),
            messages=conversations[CallSid],
        )
        reply = ai_response.content[0].text
    except Exception:
        log.exception(f"[{CallSid}] Eroare Claude API")
        _cleanup(CallSid)
        return _twiml_say_hangup(
            "Avem o problemă tehnică momentan. Vă rugăm sunați din nou."
        )

    log.info(f"[{CallSid}] SOFIA: {reply!r}")

    if "TRANSFER_TO_HUMAN" in reply:
        spoken = _strip_formatting(reply.replace("TRANSFER_TO_HUMAN", "").strip()) or "Vă transfer acum."
        _cleanup(CallSid)
        return _twiml_transfer(spoken)

    if "RESCHEDULE_APPOINTMENT:" in reply:
        spoken_part, res_json_str = reply.split("RESCHEDULE_APPOINTMENT:", 1)
        spoken_part = _strip_formatting(spoken_part.strip())
        res = _extract_json(res_json_str)

        if not res:
            log.warning(f"[{CallSid}] JSON invalid în RESCHEDULE: {res_json_str!r}")
            _cleanup(CallSid)
            return _twiml_transfer("Am o problemă cu datele reprogramării. Vă transfer.")

        try:
            duration = int(res.get("duration", 60))
            log.info(
                f"[{CallSid}] Reprogramare: {res['name']} | {res['old_date']} {res['old_time']} -> {res['new_date']} {res['new_time']}"
            )

            success, phone = reschedule_appointment(
                res["name"], res["old_date"], res["old_time"],
                res["new_date"], res["new_time"], duration,
            )

            if success:
                msg = f"Reprogramarea a fost făcută. Noua programare: {res['new_date']} la ora {res['new_time']}."
                if phone:
                    try:
                        send_confirmare(
                            _format_phone(phone), res["name"], "Reprogramare",
                            res["new_date"], res["new_time"], duration,
                        )
                    except Exception as sms_err:
                        log.warning(f"[{CallSid}] Eroare SMS reprogramare: {sms_err}")
                _cleanup(CallSid)
                return _twiml_say_hangup(f"{spoken_part} {msg} O zi bună!".strip())

            elif phone == "ocupat":
                free = get_free_slots(res["new_date"], duration)
                optiuni = ", ".join(free[:4]) if free else "nicio oră liberă"
                msg = f"Ora {res['new_time']} e ocupată. Ore disponibile: {optiuni}."
                conversations[CallSid].append({"role": "assistant", "content": msg})
                return _twiml_gather(msg, timeout=6)

            else:
                _cleanup(CallSid)
                return _twiml_transfer("A apărut o problemă cu reprogramarea. Vă transfer.")

        except Exception:
            log.exception(f"[{CallSid}] Eroare în reprogramare")
            _cleanup(CallSid)
            return _twiml_transfer("Problemă la reprogramare. Vă transfer.")

    if "CANCEL_APPOINTMENT:" in reply:
        spoken_part, cancel_json_str = reply.split("CANCEL_APPOINTMENT:", 1)
        spoken_part = _strip_formatting(spoken_part.strip())
        cancel = _extract_json(cancel_json_str)

        if not cancel:
            log.warning(f"[{CallSid}] JSON invalid în CANCEL: {cancel_json_str!r}")
            _cleanup(CallSid)
            return _twiml_transfer("Am o problemă cu datele anulării. Vă transfer.")

        try:
            serviciu = cancel.get("service", "consultație")
            log.info(
                f"[{CallSid}] Anulare: {cancel['name']} | {serviciu} | {cancel['date']} {cancel['time']}"
            )

            phone = cancel_appointment(cancel["name"], cancel["date"], cancel["time"])
            msg = f"Programarea pentru {serviciu} din {cancel['date']} la ora {cancel['time']} a fost anulată."

            if phone:
                try:
                    send_anulare(
                        _format_phone(phone), cancel["name"], serviciu,
                        cancel["date"], cancel["time"],
                    )
                except Exception as sms_err:
                    log.warning(f"[{CallSid}] Eroare SMS anulare: {sms_err}")

            _cleanup(CallSid)
            return _twiml_say_hangup(f"{spoken_part} {msg} O zi bună!".strip())

        except Exception:
            log.exception(f"[{CallSid}] Eroare în anulare")
            _cleanup(CallSid)
            return _twiml_transfer("A apărut o problemă. Vă transfer la echipă.")

    if "BOOK_APPOINTMENT:" in reply:
        spoken_part, booking_json_str = reply.split("BOOK_APPOINTMENT:", 1)
        spoken_part = _strip_formatting(spoken_part.strip())
        booking = _extract_json(booking_json_str)

        if not booking:
            log.warning(f"[{CallSid}] JSON invalid în BOOK: {booking_json_str!r}")
            _cleanup(CallSid)
            return _twiml_transfer("Am o problemă cu datele programării. Vă transfer.")

        try:
            service = booking.get("service", "Consultație")
            duration = infer_duration(service)
            phone = booking.get("phone", "")

            log.info(
                f"[{CallSid}] Booking: {booking['name']} | {service} ({duration}min) | {booking['date']} {booking['time']} | {phone}"
            )

            success = book_appointment(
                name=booking["name"],
                service=service,
                date=booking["date"],
                time=booking["time"],
                duration=duration,
                phone=phone,
            )

            if success:
                confirmare = (
                    f"Excelent. Programare confirmată: {service} pe "
                    f"{booking['date']} la {booking['time']}, {duration} minute."
                )
                if phone:
                    try:
                        send_confirmare(
                            _format_phone(phone), booking["name"], service,
                            booking["date"], booking["time"], duration,
                        )
                    except Exception as sms_err:
                        log.warning(f"[{CallSid}] Eroare SMS confirmare: {sms_err}")
                _cleanup(CallSid)
                return _twiml_say_hangup(f"{spoken_part} {confirmare} O zi bună!".strip())

            else:
                free = get_free_slots(booking["date"], duration)
                if free:
                    optiuni = ", ".join(free[:4])
                    msg = (
                        f"Ora {booking['time']} este ocupată. "
                        f"Ore disponibile pe {booking['date']}: {optiuni}. Ce preferați?"
                    )
                else:
                    msg = f"Ziua de {booking['date']} este complet ocupată. Doriți altă zi?"
                conversations[CallSid].append({"role": "assistant", "content": msg})
                return _twiml_gather(msg, timeout=6)

        except Exception:
            log.exception(f"[{CallSid}] Eroare în booking")
            _cleanup(CallSid)
            return _twiml_transfer("A apărut o problemă. Vă transfer la echipă.")

    clean_reply = _strip_formatting(reply)
    conversations[CallSid].append({"role": "assistant", "content": reply})
    return _twiml_gather(clean_reply, timeout=5)


@app.post("/call-ended")
async def call_ended(CallSid: str = Form(...)):
    log.info(f"[{CallSid}] Call ended")
    _cleanup(CallSid)
    return {"status": "ok"}


def _cleanup(call_sid: str):
    conversations.pop(call_sid, None)
