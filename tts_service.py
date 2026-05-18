import os
import uuid
import httpx
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("sofia.tts")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# Flash v2.5 = latență ~75ms, suportă română, perfect pentru telefonie
MODEL_ID = "eleven_flash_v2_5"

AUDIO_DIR = Path("/tmp/sofia_audio")
AUDIO_DIR.mkdir(exist_ok=True)


async def generate_audio_async(text: str) -> str | None:
    """Generează audio cu ElevenLabs. Returnează numele fișierului sau None la eșec."""
    if not ELEVENLABS_API_KEY:
        log.warning("ELEVENLABS_API_KEY lipsește - fallback la Polly")
        return None

    if not text or not text.strip():
        return None

    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = AUDIO_DIR / filename

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    # mp3_22050_32 = format optim pentru Twilio (calitate bună, fișier mic)
    params = {"output_format": "mp3_22050_32"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, headers=headers, json=payload, params=params)
            r.raise_for_status()
            filepath.write_bytes(r.content)
        log.info(f"[TTS] Audio generat: {filename} ({len(r.content)} bytes)")
        _cleanup_old_files()
        return filename
    except Exception as e:
        log.exception(f"[TTS] Eroare generare: {e}")
        return None


def _cleanup_old_files(max_age_seconds: int = 600):
    """Șterge fișierele audio mai vechi de 10 minute."""
    import time
    now = time.time()
    for f in AUDIO_DIR.glob("*.mp3"):
        try:
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink()
        except Exception:
            pass
