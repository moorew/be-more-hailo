from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import logging
import os
import json
import uuid
import requests
import shutil
import numpy as np
import psutil
import subprocess

# Import our new unified core modules
from core.llm import Brain, strip_prompt_leakage
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

import time as _time
from collections import deque
recent_thoughts = deque(maxlen=20) # Cache last 20 thoughts to avoid repeats

AUDIO_DIR = os.path.join("static", "audio")
AUDIO_MAX_AGE_SECONDS = 300  # 5 minutes

def _cleanup_old_audio():
    """Remove generated audio files older than AUDIO_MAX_AGE_SECONDS."""
    try:
        now = _time.time()
        for f in os.listdir(AUDIO_DIR):
            if not f.startswith("response_"):
                continue
            fpath = os.path.join(AUDIO_DIR, f)
            if now - os.path.getmtime(fpath) > AUDIO_MAX_AGE_SECONDS:
                os.remove(fpath)
    except Exception as e:
        logger.warning(f"Audio cleanup error: {e}")

@app.on_event("startup")
async def startup_cleanup():
    _cleanup_old_audio()

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

    # Check if the response is a pure action JSON (play_music, display_image, take_photo)
    # These are handled client-side — skip TTS generation for them
    is_action = False
    try:
        action_data = json.loads(content)
        if isinstance(action_data, dict) and "action" in action_data:
            is_action = True
            logger.info(f"Action response detected: {action_data.get('action')} — skipping TTS")
    except (json.JSONDecodeError, ValueError):
        pass

    audio_url = None

    if not is_action:
        # Clean text for TTS (applies pronunciation replacements like BMO->beemo).
        # Keep the original content for display so the user sees "BMO" not "beemo".
        tts_content = clean_text_for_speech(content)
        if not tts_content:
            tts_content = content  # fallback to raw if cleaning strips everything

        # Periodically clean up old audio files
        background_tasks.add_task(_cleanup_old_audio)

        if play_on_hardware:
            # Play on Pi speakers in the background so we don't block the UI response
            background_tasks.add_task(play_audio_on_hardware, tts_content)
        else:
            # Generate a WAV file for the browser to play
            filename = f"response_{uuid.uuid4().hex[:8]}.wav"
            audio_url = generate_audio_file(tts_content, filename)

    return {
        "response": content,
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
        except Exception:
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
    # Prevent path traversal by rejecting any path separators
    if "/" in state or "\\" in state or ".." in state:
        return {"images": []}
    face_dir = os.path.join("faces", state)
    if not os.path.exists(face_dir) or not os.path.isdir(face_dir):
        return {"images": []}

    images = [f"/faces/{state}/{img}" for img in os.listdir(face_dir) if img.endswith(('.png', '.jpg', '.jpeg'))]
    return {"images": sorted(images)}

@app.get("/api/sounds/{category}")
async def get_sounds(category: str):
    """
    Returns a list of sound paths for a given category (greeting_sounds, ack_sounds, thinking_sounds)
    """
    # Prevent path traversal by rejecting any path separators
    if "/" in category or "\\" in category or ".." in category:
        return {"sounds": []}
    sound_dir = os.path.join("sounds", category)
    if not os.path.exists(sound_dir) or not os.path.isdir(sound_dir):
        return {"sounds": []}

    sounds = [f"/sounds/{category}/{s}" for s in os.listdir(sound_dir) if s.endswith('.wav')]
    return {"sounds": sorted(sounds)}

@app.get("/api/screensaver-thought")
async def get_screensaver_thought():
    """Generate a random BMO thought for the web screensaver.
    Uses web search + local LLM."""
    import random
    import re
    from core.search import search_web, search_images
    from core.config import LLM_URL, FAST_LLM_MODEL

    fallback_phrases = [
        "I wonder what Finn and Jake are doing right now.",
        "Does anyone want to play a video game? No? ...Okay.",
        "La la la la la... BMO is the best!",
        "Sometimes BMO just likes to hum a little tune.",
        "Football... is a tough little guy.",
        "Is it time for a video game yet? I have a new one!",
        "I hope everyone is having a wonderful day. Especially you!",
        "Sometimes I like to just sit and think about... well, everything!",
        "Being a robot is pretty cool, but being BMO is even better!",
    ]

    phrase = None
    image_url = None

    try:
        # 1. Ask the LLM for a random, weird, or interesting topic to search for
        # This ensures the thoughts are always fresh and diverse.
        topic = None
        try:
            topic_messages = [
                {"role": "system", "content": "You are BMO's brain. Suggest one very specific, random, and interesting topic for BMO to learn about today. Examples: 'history of the first toaster', 'why do wombats have square poop', 'the mystery of the Voynich manuscript'. Keep it under 10 words. Provide ONLY the topic, no quotes or preamble."},
                {"role": "user", "content": "Give me a random topic."}
            ]
            topic_payload = {
                "model": FAST_LLM_MODEL,
                "messages": topic_messages,
                "stream": False,
                "options": {"temperature": 1.0, "num_predict": 20}
            }
            import requests as http_requests
            topic_resp = http_requests.post(LLM_URL, json=topic_payload, timeout=10)
            if topic_resp.status_code == 200:
                topic = topic_resp.json().get("message", {}).get("content", "").strip().strip('"').strip("'")
                # Remove any BMO tags or prefix if the LLM leaked them
                topic = re.sub(r'^Topic:|^BMO topic:|^I want to learn about: ', '', topic, flags=re.IGNORECASE)
        except Exception as e:
            logger.warning(f"[SCREENSAVER-WEB] LLM topic generation failed: {e}")

        # Fallback to a fixed list if LLM fails
        if not topic or len(topic) < 3:
            search_topics = [
                "interesting fun fact of the day",
                "weather forecast today in Brantford, Ontario",
                "this day in history",
                "cool science discovery this week",
                "funny animal fact",
                "Adventure Time lore or trivia",
                "latest space news from NASA",
                "strange laws in Canada",
                "history of robots",
                "cool deep sea creatures",
                "unusual world records",
                "mysteries of the pyramids",
                "evolution of video game consoles",
                "fun facts about penguins",
            ]
            topic = random.choice(search_topics)
            # Avoid picking the same topic too often
            for _ in range(3):
                if topic in recent_thoughts:
                    topic = random.choice(search_topics)
                else:
                    break
        
        logger.info(f"[SCREENSAVER-WEB] Pondering about: {topic}")
        search_result = search_web(topic)

        if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR"):
            thought_prompt = (
                "You are BMO, a cute little robot. You just learned something interesting from the real world. "
                "Share what you found as a short, charming 'pondering' to yourself. "
                "RULES:\n"
                "1. You MUST start your response with the tag '[BMO]'. \n"
                "2. After the tag, say: 'I found this today, [Summarize the specific fact].' \n"
                "3. Then, share your own charming reaction or opinion naturally. \n"
                "4. If the topic is visual, you SHOULD include exactly one JSON action on a new line: \n"
                "   {\"action\": \"display_image\", \"subject\": \"[CUTE_WHIMSICAL_DESCRIPTION]\"} \n"
                "5. CRITICAL: Your entire response MUST be under 60 words. You must finish your thought completely. \n"
                "6. Do NOT include labels like 'Summarize:' or 'Fact:' or repeat these rules.\n"
                f"Topic: {topic}\n"
                f"Info: {search_result[:1500]}"
            )
            messages = [
                {"role": "system", "content": "You are BMO, a cute little robot who muses to yourself. Be concise, specific, and always finish your thought within 60 words. Do NOT repeat instructions."},
                {"role": "user", "content": thought_prompt},
            ]

            # Try local LLM
            try:
                payload = {
                    "model": FAST_LLM_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 512}
                }
                resp = http_requests.post(LLM_URL, json=payload, timeout=60)
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "").strip()
                    if content and "connect" not in content.lower() and "error" not in content.lower():
                        # Strip leakage and reasoning
                        phrase = strip_prompt_leakage(content)
                        if phrase:
                            recent_thoughts.append(topic)
            except Exception as e:
                logger.warning(f"[SCREENSAVER-WEB] Local LLM failed: {e}")

            # Extract image URL if present
            if phrase:
                # First, find all JSON-like blocks
                json_blocks = re.findall(r'\{.*?\}', phrase, re.DOTALL)
                for block in json_blocks:
                    try:
                        action_data = json.loads(block)
                        if action_data.get("action") == "display_image":
                            # Use DuckDuckGo to find a real image of the subject
                            subject = action_data.get("subject") or action_data.get("image_url")
                            if subject:
                                # Clean up subject if it's a URL
                                if "://" in subject:
                                    image_url = subject
                                else:
                                    # Make the search more likely to find 'imaginative' art/photos
                                    image_url = search_images(subject)
                                    
                            phrase = phrase.replace(block, '').strip()
                            break # Only one image
                        elif "action" in action_data:
                            # Remove other JSON actions from the phrase
                            phrase = phrase.replace(block, '').strip()
                    except Exception:
                        pass
                
                # Final cleanup of the phrase
                phrase = strip_prompt_leakage(phrase)
    except Exception as e:
        logger.error(f"[SCREENSAVER-WEB] Thought generation failed: {e}")

    if not phrase:
        phrase = random.choice(fallback_phrases)

    return {"thought": phrase, "image_url": image_url}

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
