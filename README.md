# ESP32 Voice Assistant — Phase 1 (No Speaker)

This is a minimal FastAPI server to receive audio from an ESP32 (INMP441 mic over I²S), run **STT (Whisper)**, ask **Gemini** for a response, and synthesize **TTS** to a WAV file on your PC.

## Features
- Web UI with **Start**, **Stop**, and **Process** buttons
- WebSocket endpoint `/ws` for ESP32 to connect
- Saves recordings under `recordings/` and replies under `responses/`
- Offline STT with Whisper (python package); requires **ffmpeg**
- LLM via Gemini (`gemini-1.5-flash` by default)
- Offline TTS via `pyttsx3` (saves WAV to `responses/`)

## Setup

1. **Install system deps**
   - Install **Python 3.10+**
   - Install **ffmpeg** (required by Whisper)
     - Windows (choco): `choco install ffmpeg`
     - macOS (brew): `brew install ffmpeg`
     - Ubuntu/Debian: `sudo apt-get install ffmpeg`

2. **Create a virtualenv and install requirements**
   ```bash
   cd esp32_voice_assistant_phase1
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Set your Gemini API key**
   ```bash
   # create a .env or set environment variable
   setx GEMINI_API_KEY "your_key_here"          # Windows PowerShell
   export GEMINI_API_KEY="your_key_here"        # macOS/Linux
   ```
   Optionally set models:
   ```bash
   export GEMINI_MODEL="gemini-1.5-flash"
   export WHISPER_MODEL="base"   # tiny/base/small
   ```

4. **Run the server**
   ```bash
   uvicorn server:app --host 0.0.0.0 --port 8080
   ```
   Then open: http://localhost:8080

## ESP32 WebSocket Protocol

- Connect the ESP32 to: `ws://<PC_IP>:8080/ws`
- The server will send `"START"` / `"STOP"` messages (text) to control recording.
- While recording is **ON**, send binary PCM chunks (16-bit, mono, 16kHz) to the WebSocket.
- The server writes those chunks into a `.wav` file.

**Arduino-style pseudocode**:
```cpp
// connect WebSocket to ws://PC_IP:8080/ws
// on message "START": start reading I2S and websocket.sendBIN(...)
// on message "STOP": stop reading/sending
```

## Workflow
1. Open the web UI and click **Start** → server begins a new WAV file and tells ESP32 to start sending.
2. Speak. Then click **Stop** → server closes the WAV.
3. Click **Process** → runs Whisper STT → Gemini LLM → TTS to `responses/reply_*.wav`.
4. Click the link to play/download the reply audio on your PC.

## Notes
- For faster STT, set `WHISPER_MODEL=tiny` (less accurate), or use GPU if available.
- For better TTS, you can later replace `pyttsx3` with **Piper TTS** or another engine.
- This is Phase 1: no speaker on ESP32. In Phase 2, you can stream the reply audio back to ESP32 and play via I²S DAC/amp.