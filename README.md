# 🦷 Recepționist AI – Ghid de Instalare (România)

## Ce ai nevoie (toate gratuite pentru început)
- Computer cu Python 3.10+
- Cont Twilio (trial gratuit) → twilio.com
- Cont Anthropic → console.anthropic.com
- Cont Google (pentru Calendar)

---

## PAS 1 — Instalează dependențele Python

```bash
pip install -r requirements.txt
```

---

## PAS 2 — Obține cheia API Anthropic

1. Mergi la https://console.anthropic.com
2. Click "API Keys" → "Create Key"
3. Copiază cheia

---

## PAS 3 — Configurează Google Calendar

1. Mergi la https://console.cloud.google.com
2. Creează un proiect nou (orice nume)
3. Caută "Google Calendar API" → Activează
4. Mergi la "Credentials" → "Create Credentials" → "Service Account"
5. Dă-i un nume → click Done
6. Click pe service account → tab "Keys" → "Add Key" → JSON
7. Descarcă fișierul și redenumește-l: credentials.json
8. Pune credentials.json ÎN ACEST FOLDER

Distribuie calendarul cu service account-ul:
1. Google Calendar pe web → Settings → "Share with specific people"
2. Adaugă email-ul service account (xxx@your-project.iam.gserviceaccount.com)
3. Permisiunea: "Make changes to events"
4. Copiază Calendar ID (din "Integrate calendar")

---

## PAS 4 — Creează fișierul .env

```bash
cp .env.example .env
```

Completează:
```
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CALENDAR_ID=your_id@group.calendar.google.com
HUMAN_PHONE_NUMBER=+40XXXXXXXXX
```

---

## PAS 5 — Pornește serverul

```bash
uvicorn main:app --reload --port 8000
```

---

## PAS 6 — Expune pe internet cu ngrok

Instalează ngrok: https://ngrok.com/download

Într-un tab nou:
```bash
ngrok http 8000
```

Copiază URL-ul (ex: https://abc123.ngrok.io)

---

## PAS 7 — Configurează Twilio

1. Creează cont la twilio.com
2. Cumpără număr românesc (+40): Phone Numbers → Buy a Number → Romania
3. Phone Numbers → Active Numbers → click numărul tău
4. Voice Configuration:
   - Webhook incoming: https://URL_NGROK/incoming-call
   - Webhook status:   https://URL_NGROK/call-ended
5. Salvează

---

## PAS 8 — Testează!

Sună numărul Twilio. Sofia răspunde în română!

---

## Vocea românească

Codul folosește Amazon Polly – Carmen (singura voce RO în Twilio).
Pentru voce mai naturală în viitor: integrare ElevenLabs cu voce custom.

---

## Personalizare

Editează SYSTEM_PROMPT în main.py pentru a schimba:
- Numele și adresa clinicii
- Servicii, prețuri, program
- Tonul Sofiei

---

## Deployment producție

Railway (railway.app) ~$5/lună — cel mai simplu.
Push codul, actualizează webhook-urile Twilio cu noul URL.

---

## Costuri estimate (~200 apeluri/lună)

Twilio (număr + minute):  ~$10-13
Claude API:               ~$3-4
Google Calendar:          Gratuit
Railway hosting:          ~$5
TOTAL:                    ~$20/lună

Vinzi serviciul cu 200-500 EUR/lună per clinică.
