from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import requests
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BMO Web UI")

# Mount static files (for CSS, JS, and images)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/faces", StaticFiles(directory="faces"), name="faces")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Configuration for Hailo/Ollama
LLM_URL = "http://127.0.0.1:8000/api/chat" # Adjust if the Hailo endpoint is different
LLM_MODEL = "llama3.2:3b" # Adjust to your specific Hailo model name

class ChatRequest(BaseModel):
    message: str
    history: list = []

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Send text to local LLM (Hailo/Ollama) and get response.
    """
    user_text = request.message
    history = request.history
    
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
            return {"response": content, "history": history}
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
