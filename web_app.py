from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import requests
import logging
import os
import subprocess
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BMO Web UI")

# Ensure audio directory exists
os.makedirs("static/audio", exist_ok=True)

# Mount static files (for CSS, JS, images, and audio)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/faces", StaticFiles(directory="faces"), name="faces")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Configuration for Hailo/Ollama
LLM_URL = "http://127.0.0.1:8000/api/chat" # Adjust if the Hailo endpoint is different
LLM_MODEL = "llama3.2:3b" # Adjust to your specific Hailo model name

# Configuration for Piper TTS
PIPER_CMD = "./piper/piper"
PIPER_MODEL = "./piper/en_GB-semaine-medium.onnx"

class ChatRequest(BaseModel):
    message: str
    history: list = []
    play_on_hardware: bool = False

def play_audio_on_hardware(text: str):
    """Plays audio directly out of the Pi's speakers using Piper and aplay."""
    try:
        logger.info(f"Playing audio on hardware: {text[:30]}...")
        # Escape single quotes in text to prevent shell injection
        safe_text = text.replace("'", "'\\''")
        piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_raw | aplay -r 22050 -f S16_LE -t raw"
        subprocess.run(piper_cmd, shell=True, check=True)
    except Exception as e:
        logger.error(f"Hardware TTS Error: {e}")

def generate_audio_file(text: str, filename: str):
    """Generates a WAV file using Piper for the browser to play."""
    try:
        logger.info(f"Generating audio file: {filename}")
        safe_text = text.replace("'", "'\\''")
        filepath = os.path.join("static", "audio", filename)
        piper_cmd = f"echo '{safe_text}' | {PIPER_CMD} --model {PIPER_MODEL} --output_file {filepath}"
        subprocess.run(piper_cmd, shell=True, check=True)
        return f"/static/audio/{filename}"
    except Exception as e:
        logger.error(f"File TTS Error: {e}")
        return None

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Send text to local LLM (Hailo/Ollama) and get response.
    """
    user_text = request.message
    history = request.history
    play_on_hardware = request.play_on_hardware
    
    # Ensure system prompt is present
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": "You are BMO, a helpful robot assistant. Keep answers short and fun."})
        
    history.append({"role": "user", "content": user_text})

    payload = {
        "model": LLM_MODEL,
        "messages": history,
        "stream": False
    }

    try:
        logger.info(f"Sending request to LLM: {LLM_URL}")
        response = requests.post(LLM_URL, json=payload, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("message", {}).get("content", "")
            history.append({"role": "assistant", "content": content})
            
            audio_url = None
            
            if play_on_hardware:
                # Play on Pi speakers in the background so we don't block the UI response
                background_tasks.add_task(play_audio_on_hardware, content)
            else:
                # Generate a WAV file for the browser to play
                # We do this synchronously so the browser gets the URL immediately
                filename = f"response_{uuid.uuid4().hex[:8]}.wav"
                audio_url = generate_audio_file(content, filename)
                
            return {
                "response": content, 
                "history": history,
                "audio_url": audio_url
            }
        else:
            logger.error(f"LLM Error: {response.status_code} - {response.text}")
            return {"error": f"LLM Error: {response.status_code}", "history": history}
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Connection Error: {e}")
        return {"error": "Could not connect to the LLM. Is the Hailo server running?", "history": history}
    except Exception as e:
        logger.error(f"Brain Exception: {e}")
        return {"error": "An unexpected error occurred.", "history": history}

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

if __name__ == "__main__":
    import uvicorn
    # Run on all interfaces (0.0.0.0) so it can be accessed from other machines on the network
    uvicorn.run(app, host="0.0.0.0", port=8080)
