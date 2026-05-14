from fastapi import FastAPI, Form, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from anthropic import Anthropic
from dotenv import load_dotenv
from calendar_service import book_appointment, get_available_slots
from datetime import date
import json
import os

load_dotenv()

app = FastAPI()
claude = Anthropic()
conversations = {}

ZILE_RO = {
    "Monday": "Luni", "Tuesday": "Marți", "Wednesday": "Miercuri",
    "Thursday": "Joi", "Friday": "Vineri", "Saturday": "Sâmbătă", "Sunday": "Duminică"
}
LUNI_RO = {
    "January": "ianuarie", "February": "februarie", "March": "martie",
    "April": "aprilie", "May": "mai", "June": "iunie",
    "July": "iulie", "August": "august", "September": "septembrie",
    "October": "octombrie", "November": "noiembrie", "December": "decembrie"
}

def get_system_prompt():
    azi = date.today()
    zi_saptamana = ZILE_RO[azi.strftime("%A")]
    luna = LUNI_RO[azi.strftime("%B")]
    data_azi = f"{zi_saptamana}, {azi.day} {luna} {azi.year}"
    data_iso = azi.strftime("%Y-%m-%d")

    return f"""Ești Sofia, recepționista AI prietenoasă a Clinicii Stomatologice Zâmbet Frumos din București.

VORBEȘTI DOAR ÎN ROMÂNĂ. Indiferent de ce spune pacientul, răspunzi mereu în română.

DATA DE AZI ESTE: {data_azi} ({data_iso})
Când pacientul spune "joi viitoare", "săptămâna viitoare", "mâine", "poimâine" etc,
calculează data corectă față de data de azi ({data_iso}) și folosește formatul YYYY-MM-DD.

INFORMAȚII CLINICĂ:
- Nume: Clinica Stomatologică Zâmbet Frumos
- Adresă: Strada Florilor nr. 12, Sector 2, București
- Program: Luni–Vineri 08:00–19:00, Sâmbătă 09:00–14:00, Duminică închis
- Telefon urgențe (uman): +40 21 555 0100
- Asigurări acceptate: CNAS, Regina Maria, Medicover, MedLife, Groupama

SERVICII ȘI DURATE TIPICE:
- Detartraj (curățare profesională)  → 45 min  (250 RON fără asigurare)
- Consultație generală               → 30 min  (150 RON fără asigurare)
- Plombă (obturaţie)                 → 60 min  (300–500 RON în funcție de dinte)
- Albire dentară                     → 60 min  (800 RON)
- Urgență / Durere de dinte          → 30 min  (walk-in binevenit, sunați înainte)
- Consultație implant dentar         → 30 min  (150 RON)
- Extracție dentară                  → 45 min  (200–400 RON)

FLUXUL PROGRAMĂRII — colectează TOATE informațiile:
1. Numele complet al pacientului
2. Ce serviciu dorește
3. Data preferată (calculează corect față de azi!) și ora (HH:MM, 24h)
4. Durata — sugerează durata tipică, acceptă doar: 30, 45 sau 60 de minute

Când ai toate informațiile, termină mesajul cu:
BOOK_APPOINTMENT:{{"name":"Ion Popescu","service":"Detartraj","date":"2026-05-07","time":"10:00","duration":45}}

URGENȚE: Durere severă, umflătură, dinte rupt → empatie imediată + slot în aceeași zi.
În afara programului → "Mergeți la urgențe stomatologice sau sunați 112."

ASIGURĂRI: Acceptăm CNAS, Regina Maria, Medicover, MedLife, Groupama.
Aduceți cardul de asigurare. Oferim și rate pentru neasigurați.

REGULI:
- Răspunsuri SCURTE — este un apel telefonic
- Fii caldă și reconfortantă
- Nu inventa prețuri sau proceduri
- Dacă nu ești sigură: "Lăsați-mă să vă conectez cu echipa noastră." + TRANSFER_TO_HUMAN
"""


@app.post("/incoming-call")
async def incoming_call():
    response = VoiceResponse()
    gather = Gather(input="speech", action="/handle-speech", timeout=5, speech_timeout="auto", language="ro-RO")
    gather.say("Bună ziua! Ați sunat la Clinica Stomatologică Zâmbet Frumos. Sunt Sofia, asistenta dumneavoastră virtuală. Cu ce vă pot ajuta?", voice="Polly.Carmen")
    response.append(gather)
    response.say("Nu am auzit nimic. Vă rugăm să sunați din nou. Mulțumim!", voice="Polly.Carmen")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-speech")
async def handle_speech(CallSid: str = Form(...), SpeechResult: str = Form(default="")):
    response = VoiceResponse()

    if not SpeechResult.strip():
        gather = Gather(input="speech", action="/handle-speech", timeout=5, speech_timeout="auto", language="ro-RO")
        gather.say("Scuze, nu v-am auzit. Puteți repeta, vă rog?", voice="Polly.Carmen")
        response.append(gather)
        return Response(content=str(response), media_type="application/xml")

    if CallSid not in conversations:
        conversations[CallSid] = []
    conversations[CallSid].append({"role": "user", "content": SpeechResult})

    ai_response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=get_system_prompt(),
        messages=conversations[CallSid]
    )
    reply = ai_response.content[0].text

    if "TRANSFER_TO_HUMAN" in reply:
        spoken = reply.replace("TRANSFER_TO_HUMAN", "").strip()
        response.say(spoken, voice="Polly.Carmen")
        response.dial(os.getenv("HUMAN_PHONE_NUMBER", "+40215550100"))
        _cleanup(CallSid)
        return Response(content=str(response), media_type="application/xml")

    if "BOOK_APPOINTMENT:" in reply:
        spoken_part, booking_json = reply.split("BOOK_APPOINTMENT:", 1)
        spoken_part = spoken_part.strip()
        try:
            booking = json.loads(booking_json.strip())
            duration = int(booking.get("duration", 60))
            if duration not in (30, 45, 60):
                duration = 60
            success = book_appointment(
                name=booking["name"],
                service=booking.get("service", "Consultație"),
                date=booking["date"],
                time=booking["time"],
                duration=duration
            )
            if success:
                spoken_part += f" Excelent! Am înregistrat programarea pentru {booking.get('service','consultație')} pe {booking['date']} la ora {booking['time']}, pentru {duration} minute. Ne vedem atunci!"
            else:
                spoken_part += " Îmi pare rău, a apărut o problemă. Vă transfer la echipa noastră."
        except Exception as e:
            print(f"Eroare programare: {e}")
            spoken_part += " A apărut o mică problemă. Vă transfer acum."

        response.say(spoken_part, voice="Polly.Carmen")
        response.say("Vă mulțumim că ați sunat. O zi bună!", voice="Polly.Carmen")
        _cleanup(CallSid)
        return Response(content=str(response), media_type="application/xml")

    conversations[CallSid].append({"role": "assistant", "content": reply})
    gather = Gather(input="speech", action="/handle-speech", timeout=6, speech_timeout="auto", language="ro-RO")
    gather.say(reply, voice="Polly.Carmen")
    response.append(gather)
    response.say("Vă mulțumim că ați sunat. O zi bună!", voice="Polly.Carmen")
    return Response(content=str(response), media_type="application/xml")


@app.post("/call-ended")
async def call_ended(CallSid: str = Form(...)):
    _cleanup(CallSid)
    return {"status": "ok"}


def _cleanup(call_sid: str):
    conversations.pop(call_sid, None)
