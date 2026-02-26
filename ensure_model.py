import sys
import json
import time
import urllib.request
import urllib.error

# Config
# Should match what's in agent.py or be passed in
# But for simplicity, we hardcode the defaults for the Hailo setup
OLLAMA_HOST = "http://localhost:8000"
REQUIRED_MODEL = "qwen2.5-instruct:1.5b"

def get_installed_models():
    try:
        url = f"{OLLAMA_HOST}/api/tags"
        print(f"DEBUG: Querying {url}")
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                raw_data = response.read().decode()
                print(f"DEBUG: Raw server response: {raw_data}")
                data = json.loads(raw_data)
                
                # Standard Ollama structure
                if 'models' in data:
                    return [m['name'] for m in data.get('models', [])]
                
                # Fallback: maybe it returns a simple list?
                if isinstance(data, list):
                    return [m.get('name', m) if isinstance(m, dict) else m for m in data]
                    
                print(f"DEBUG: Unexpected JSON structure: {data.keys()}")
                return []
    except urllib.error.URLError as e:
        print(f"Connection error: {e}")
        return None
    except Exception as e:
        print(f"Error checking models: {e}")
        return None

def pull_model(model_name):
    print(f"Triggering pull for {model_name}...")
    url = f"{OLLAMA_HOST}/api/pull"
    data = json.dumps({"model": model_name, "stream": True}).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    
    try:
        with urllib.request.urlopen(req) as response:
            print("Download started. Tracking progress...")
            # stream output
            for line in response:
                try:
                    line_data = json.loads(line.decode())
                    status = line_data.get('status', '')
                    completed = line_data.get('completed', 0)
                    total = line_data.get('total', 1)
                    if total > 0:
                        percent = (completed / total) * 100
                        print(f"\rStatus: {status} - {percent:.1f}%", end="")
                    else:
                        print(f"\rStatus: {status}", end="")
                except:
                    pass
            print("\nDownload complete.")
            return True
    except urllib.error.HTTPError as e:
        print(f"\nFailed to pull model: HTTP {e.code} - {e.reason}")
        # If 404, maybe the model tag is wrong for this specific server?
        return False
    except Exception as e:
        print(f"\nError during pull: {e}")
        return False

def main():
    print(f"Checking for model '{REQUIRED_MODEL}' on {OLLAMA_HOST}...")
    
    # 1. Check if server is up
    models = get_installed_models()
    if models is None:
        print(f"ERROR: Could not connect to Hailo-Ollama server at {OLLAMA_HOST}")
        print("Please ensure the server is running (e.g., 'hailo-ollama serve').")
        sys.exit(1)
        
    # 2. Check if model exists
    if REQUIRED_MODEL in models:
        print(f"Model '{REQUIRED_MODEL}' is ready.")
        sys.exit(0)
    
    print(f"Model '{REQUIRED_MODEL}' not found. Installed: {models}")
    
    # 3. Try to pull
    if pull_model(REQUIRED_MODEL):
        print("Model successfully installed.")
        sys.exit(0)
    else:
        print("Failed to install model.")
        sys.exit(1)

if __name__ == "__main__":
    main()
