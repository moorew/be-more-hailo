from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import logging
import os
import uuid
import requests
import shutil

# Import our new unified core modules
from core.llm import Brain
from core.tts import play_audio_on_hardware, generate_audio_file, add_pronunciation, load_pronunciations
from core.stt import transcribe_audio
from core.config import LLM_URL

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

class ChatRequest(BaseModel):
    message: str
    history: list = []
    play_on_hardware: bool = False

class PronunciationRequest(BaseModel):
    word: str
    phonetic: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/pronunciation")
async def add_pronunciation_rule(request: PronunciationRequest):
    """Add a new pronunciation rule."""
    add_pronunciation(request.word, request.phonetic)
    return {"status": "success", "word": request.word, "phonetic": request.phonetic}

@app.get("/api/pronunciation")
async def get_pronunciations():
    """Get all pronunciation rules."""
    return load_pronunciations()

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

    # Get response from LLM
    content = brain.think(user_text)
    
    # Check if there was an error
    if content.startswith("Error:") or content.startswith("Could not connect") or content.startswith("I'm having trouble"):
        return {"error": content, "history": brain.get_history()}
        
    audio_url = None
    
    if play_on_hardware:
        # Play on Pi speakers in the background so we don't block the UI response
        background_tasks.add_task(play_audio_on_hardware, content)
    else:
        # Generate a WAV file for the browser to play
        filename = f"response_{uuid.uuid4().hex[:8]}.wav"
        audio_url = generate_audio_file(content, filename)
        
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

if __name__ == "__main__":
    import uvicorn
    # Run on all interfaces (0.0.0.0) so it can be accessed from other machines on the network
    uvicorn.run(app, host="0.0.0.0", port=8080)
