from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import logging
import os
import uuid
import requests
import shutil
import numpy as np
import psutil
import subprocess

# Import our new unified core modules
from core.llm import Brain
from core.tts import play_audio_on_hardware, generate_audio_file, add_pronunciation, load_pronunciations, clean_text_for_speech
from core.stt import transcribe_audio
from core.config import LLM_URL, WAKE_WORD_MODEL, WAKE_WORD_THRESHOLD

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to load openwakeword for web streaming
try:
    from openwakeword.model import Model
    # Initialize the model once for the web app
    oww_model = Model(wakeword_model_paths=[WAKE_WORD_MODEL])
    logger.info(f"Loaded OpenWakeWord model: {WAKE_WORD_MODEL}")
except Exception as e:
    logger.warning(f"Could not load OpenWakeWord for web app: {e}")
    oww_model = None

app = FastAPI(title="BMO Web UI")

# Ensure audio directory exists
os.makedirs("static/audio", exist_ok=True)

# Mount static files (for CSS, JS, images, and audio)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/faces", StaticFiles(directory="faces"), name="faces")
app.mount("/sounds", StaticFiles(directory="sounds"), name="sounds")

# Setup templates
templates = Jinja2Templates(directory="templates")

class ChatRequest(BaseModel):
    message: str
    history: list = []
    play_on_hardware: bool = False
    image: str = None # Optional base64 image for vision tasks

class PronunciationRequest(BaseModel):
    word: str
    phonetic: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/favicon.png")
async def get_favicon():
    return FileResponse("favicon.png")

@app.post("/api/pronunciation")
async def add_pronunciation_rule(request: PronunciationRequest):
    """Add a new pronunciation rule."""
    add_pronunciation(request.word, request.phonetic)
    return {"status": "success", "word": request.word, "phonetic": request.phonetic}

@app.get("/api/pronunciation")
async def get_pronunciations():
    """Get all pronunciation rules."""
    return load_pronunciations()

@app.get("/api/debug")
async def get_debug_info():
    """Get system diagnostics and Hailo status."""
    info = {
        "status": "online",
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent
        },
        "hailo": {
            "status": "unknown",
            "error": None
        },
        "logs": []
    }
    
    # Check Hailo/Ollama status
    try:
        # Extract base URL from LLM_URL (e.g., http://127.0.0.1:8000)
        base_url = LLM_URL.split("/api/")[0]
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        if response.status_code == 200:
            info["hailo"]["status"] = "online"
        else:
            info["hailo"]["status"] = f"error ({response.status_code})"
    except Exception as e:
        info["hailo"]["status"] = "offline"
        info["hailo"]["error"] = str(e)
        
    # Get recent logs from journalctl
    try:
        result = subprocess.run(
            ["journalctl", "-u", "bmo-web", "-n", "10", "--no-pager"],
            capture_output=True, text=True, timeout=2
        )
        info["logs"] = result.stdout.splitlines()
    except Exception as e:
        info["logs"] = [f"Could not fetch logs: {e}"]
        
    return info

@app.post("/api/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Send text to local LLM (Hailo/Ollama) and get response.
    """
    user_text = request.message
    play_on_hardware = request.play_on_hardware
    
    # Initialize brain and load history
    brain = Brain()
    brain.set_history(request.history)

    # If an image is provided, use the vision model
    if request.image:
        logger.info("Received image for vision analysis.")
        content = brain.analyze_image(request.image, user_text)
    else:
        # Get response from LLM (includes keyword-triggered search and camera detection)
        content = brain.think(user_text)
    
    # Check if there was an error
    if content.startswith("Error:") or content.startswith("Could not connect") or content.startswith("I'm having trouble"):
        return {"error": content, "history": brain.get_history()}

    # Strip markdown formatting — the model sometimes emits bold/headers/lists
    # that look like raw code in the chat UI and break TTS.
    clean_content = clean_text_for_speech(content)
    if not clean_content:
        clean_content = content  # fallback to raw if cleaning strips everything
        
    audio_url = None
    
    if play_on_hardware:
        # Play on Pi speakers in the background so we don't block the UI response
        background_tasks.add_task(play_audio_on_hardware, clean_content)
    else:
        # Generate a WAV file for the browser to play
        filename = f"response_{uuid.uuid4().hex[:8]}.wav"
        audio_url = generate_audio_file(clean_content, filename)
        
    return {
        "response": clean_content, 
        "history": brain.get_history(),
        "audio_url": audio_url
    }


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """
    Receive an audio file from the browser, save it temporarily,
    and transcribe it using whisper.cpp.
    """
    temp_filename = f"temp_{uuid.uuid4().hex}.webm"
    temp_filepath = os.path.join("static", "audio", temp_filename)
    
    try:
        # Save the uploaded file
        with open(temp_filepath, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
            
        # Transcribe it
        text = transcribe_audio(temp_filepath)
        
        return {"text": text}
    except Exception as e:
        logger.error(f"Transcription endpoint error: {e}")
        return {"error": str(e)}
    finally:
        # Clean up the original uploaded file
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except Exception as e:
                logger.warning(f"Could not remove temp file {temp_filepath}: {e}")

@app.websocket("/api/wakeword")
async def websocket_wakeword(websocket: WebSocket):
    """
    WebSocket endpoint for continuous audio streaming from the browser.
    Expects 16kHz 16-bit PCM audio chunks.
    """
    await websocket.accept()
    if oww_model is None:
        await websocket.send_json({"error": "Wake word model not loaded on server."})
        await websocket.close()
        return

    try:
        while True:
            # Receive binary audio data (Int16 PCM)
            data = await websocket.receive_bytes()
            
            # Convert bytes to numpy array
            audio_chunk = np.frombuffer(data, dtype=np.int16)
            
            # Feed to openwakeword
            oww_model.predict(audio_chunk)
            
            # Check predictions
            for key in oww_model.prediction_buffer.keys():
                if oww_model.prediction_buffer[key][-1] > WAKE_WORD_THRESHOLD:
                    logger.info(f"Web Wake Word Detected: {key}")
                    await websocket.send_json({"event": "wakeword_detected", "model": key})
                    oww_model.reset()
                    break # Only trigger once per chunk
                    
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass

@app.get("/api/status")
async def get_status():
    """Check if the Hailo LLM server is reachable."""
    try:
        # Check the base Ollama URL (e.g., http://127.0.0.1:8000)
        base_url = LLM_URL.replace("/api/chat", "")
        response = requests.get(base_url, timeout=2)
        if response.status_code == 200:
            return {"status": "online"}
    except Exception:
        pass
    return {"status": "offline"}

@app.get("/api/faces/{state}")
async def get_face(state: str):
    """
    Returns a list of image paths for a given state (idle, thinking, speaking, etc.)
    """
    face_dir = os.path.join("faces", state)
    if not os.path.exists(face_dir):
        return {"images": []}
        
    images = [f"/faces/{state}/{img}" for img in os.listdir(face_dir) if img.endswith(('.png', '.jpg', '.jpeg'))]
    return {"images": sorted(images)}

@app.get("/api/sounds/{category}")
async def get_sounds(category: str):
    """
    Returns a list of sound paths for a given category (greeting_sounds, ack_sounds, thinking_sounds)
    """
    sound_dir = os.path.join("sounds", category)
    if not os.path.exists(sound_dir):
        return {"sounds": []}

    sounds = [f"/sounds/{category}/{s}" for s in os.listdir(sound_dir) if s.endswith('.wav')]
    return {"sounds": sorted(sounds)}

if __name__ == "__main__":
    import uvicorn
    import glob

    # Check for Tailscale SSL certificates (*.ts.net.crt / *.ts.net.key)
    cert_files = glob.glob("*.ts.net.crt")
    key_files = glob.glob("*.ts.net.key")

    if cert_files and key_files:
        cert_file = cert_files[0]
        key_file = key_files[0]
        logger.info(f"Found SSL certificates ({cert_file}). Starting securely on HTTPS...")
        uvicorn.run("web_app:app", host="0.0.0.0", port=8080, ssl_certfile=cert_file, ssl_keyfile=key_file, workers=2)
    else:
        logger.info("No SSL certificates found. Starting on HTTP...")
        # Run on all interfaces (0.0.0.0) so it can be accessed from other machines on the network
        uvicorn.run("web_app:app", host="0.0.0.0", port=8080, workers=2)
