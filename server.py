# server.py
import os, json, datetime, logging
import numpy as np, soundfile as sf, speech_recognition as sr
from fastapi import FastAPI, Request, WebSocket
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import google.generativeai as genai
from gtts import gTTS

# -------------------
# Config
# -------------------
SAMPLE_RATE = 16000
MIN_SAMPLES = SAMPLE_RATE * 2  # require at least 2 seconds of audio

RECORDINGS_DIR = "recordings"
RESPONSES_DIR = "responses"
os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(RESPONSES_DIR, exist_ok=True)

# Gemini setup
GEMINI_KEY = "AIzaSyAhkzg8OxlnvURsITfFsD8kiZi09jZuEg0"
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
else:
    print("⚠️  GEMINI_API_KEY not set! Gemini calls will fail.")
GEMINI_MODEL_NAME = "gemini-1.5-flash"

# FastAPI setup
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Globals
esp32_ws: WebSocket | None = None
ui_ws: WebSocket | None = None
recording = False
pcm_chunks: list[bytes] = []
last_transcript = ""
last_reply = ""
last_audio_url = ""

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.DEBUG)


# -------------------
# Helpers
# -------------------
def save_wav_from_chunks(chunks, out_path, samplerate=SAMPLE_RATE):
    """Concatenate PCM16 chunks -> WAV file"""
    pcm_bytes = b"".join(chunks)
    arr = np.frombuffer(pcm_bytes, dtype=np.int16)
    sf.write(out_path, arr, samplerate, subtype="PCM_16")
    return len(arr)


async def call_gemini(prompt_text: str) -> str:
    if not GEMINI_KEY:
        return "(Gemini API key not set)"
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt_text)
        return getattr(response, "text", str(response))
    except Exception as e:
        logger.exception("Gemini error")
        return f"(Gemini Error: {e})"


# -------------------
# Routes
# -------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user_text": last_transcript,
        "bot_text": last_reply,
        "audio_url": last_audio_url,
    })


@app.websocket("/ws-ui")
async def ws_ui(websocket: WebSocket):
    global recording, pcm_chunks, last_transcript, last_reply, last_audio_url
    await websocket.accept()
    ui_ws = websocket
    logger.info("🌐 Browser UI connected")

    try:
        while True:
            cmd = await websocket.receive_text()
            logger.info(f"Browser sent: {cmd}")

            if cmd == "START":
                recording = True
                pcm_chunks = []
                if esp32_ws:
                    await esp32_ws.send_text("START")
                logger.debug("🎤 Recording started")

            elif cmd == "STOP":
                recording = False
                if esp32_ws:
                    await esp32_ws.send_text("STOP")
                logger.debug("⏹ Stop received, processing audio...")

                if not pcm_chunks:
                    last_transcript = "(no audio received)"
                    last_reply = ""
                    last_audio_url = ""
                    await websocket.send_text(json.dumps({
                        "user_text": last_transcript,
                        "bot_text": last_reply,
                        "audio_url": last_audio_url
                    }))
                    continue

                # Check length
                total_bytes = len(b"".join(pcm_chunks))
                logger.debug(f"Total bytes in buffer: {total_bytes}")
                if total_bytes < MIN_SAMPLES * 2:  # 2 bytes/sample
                    last_transcript = "(STT Error: audio too short, please speak longer)"
                    last_reply = ""
                    last_audio_url = ""
                    logger.warning("Audio too short for STT")
                    await websocket.send_text(json.dumps({
                        "user_text": last_transcript,
                        "bot_text": last_reply,
                        "audio_url": last_audio_url
                    }))
                    pcm_chunks = []
                    continue

                # Save WAV
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                wav_path = os.path.join(RECORDINGS_DIR, f"rec_{ts}.wav")
                try:
                    sample_count = save_wav_from_chunks(pcm_chunks, wav_path)
                    logger.info(f"💾 Saved {wav_path} ({sample_count} samples)")
                except Exception as e:
                    logger.exception("WAV save failed")
                    last_transcript = f"(Save error: {e})"
                    last_reply = ""
                    last_audio_url = ""
                    pcm_chunks = []
                    continue

                # Run STT
                try:
                    recognizer = sr.Recognizer()
                    with sr.AudioFile(wav_path) as src:
                        audio_data = recognizer.record(src)
                        last_transcript = recognizer.recognize_google(audio_data)
                    logger.info(f"📝 Transcript: {last_transcript}")
                except sr.UnknownValueError:
                    last_transcript = "(STT Error: Could not understand audio)"
                except sr.RequestError as e:
                    last_transcript = f"(STT Error: {e})"
                except Exception as e:
                    logger.exception("STT failed")
                    last_transcript = f"(STT Error: {e})"

                # Call Gemini
                last_reply = await call_gemini(last_transcript)
                logger.info(f"🤖 Gemini: {last_reply}")

                # TTS
                try:
                    tts = gTTS(last_reply)
                    mp3_file = os.path.join(RESPONSES_DIR, f"reply_{ts}.mp3")
                    tts.save(mp3_file)
                    last_audio_url = f"/responses/reply_{ts}.mp3"
                    logger.info(f"🔊 TTS saved {mp3_file}")
                except Exception as e:
                    logger.exception("TTS failed")
                    last_audio_url = ""

                # Send result to UI
                await websocket.send_text(json.dumps({
                    "user_text": last_transcript,
                    "bot_text": last_reply,
                    "audio_url": last_audio_url
                }))

                pcm_chunks = []

    except Exception as e:
        logger.exception("UI socket error")
    finally:
        await websocket.close()
        logger.info("🌐 Browser UI disconnected")


@app.websocket("/ws")
async def ws_audio(websocket: WebSocket):
    global esp32_ws, recording, pcm_chunks
    await websocket.accept()
    esp32_ws = websocket
    logger.info("✅ ESP32 connected")

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("bytes") and recording:
                pcm_chunks.append(msg["bytes"])
                logger.debug(f"Buffered chunk size={len(msg['bytes'])}, total={len(pcm_chunks)}")
            elif msg.get("type") == "websocket.disconnect":
                logger.info("⚠️ ESP32 disconnected")
                break
    except Exception as e:
        logger.exception("ESP32 WS error")
    finally:
        esp32_ws = None
        await websocket.close()


# Serve TTS responses
app.mount("/responses", StaticFiles(directory=RESPONSES_DIR), name="responses")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=True)
