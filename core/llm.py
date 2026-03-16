import base64
import os
import subprocess
import signal
import time
import requests
import logging
import re
import json
import urllib.parse
import numpy as np
from .config import LLM_URL, LLM_MODEL, FAST_LLM_MODEL, VISION_MODEL, VLM_HEF_PATH, get_system_prompt
from .tts import add_pronunciation
from .search import search_web
from .log import bmo_print

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Hailo VLM (Vision Language Model) singleton
# --------------------------------------------------------------------------- #
# Lazy-loaded on first image analysis request.  Kept alive so subsequent
# requests don't pay the ~3 s init cost again.
_vlm_instance = None
_vlm_vdevice = None


def _get_vlm():
    """Return a (vlm, frame_shape, frame_dtype) tuple, initialising on first call."""
    global _vlm_instance, _vlm_vdevice

    if _vlm_instance is not None:
        shape = _vlm_instance.input_frame_shape()
        dtype = _vlm_instance.input_frame_format_type()
        return _vlm_instance, shape, dtype

    hef = VLM_HEF_PATH
    if not os.path.isabs(hef):
        # Resolve relative to project root (where the scripts live)
        hef = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), hef)

    if not os.path.exists(hef):
        raise FileNotFoundError(f"VLM HEF not found at {hef}. Run setup.sh to download it.")

    from hailo_platform import VDevice
    from hailo_platform.genai import VLM

    logger.info(f"Initialising Hailo VLM from {hef} ...")
    try:
        params = VDevice.create_params()
        params.group_id = "SHARED"          # coexist with hailo-ollama on the NPU
        _vlm_vdevice = VDevice(params)
        _vlm_instance = VLM(_vlm_vdevice, hef)
    except Exception:
        # Release partially-initialised resources so the device isn't leaked
        if _vlm_vdevice is not None:
            try:
                _vlm_vdevice.release()
            except Exception:
                pass
        _vlm_vdevice = None
        _vlm_instance = None
        raise

    shape = _vlm_instance.input_frame_shape()
    dtype = _vlm_instance.input_frame_format_type()
    logger.info(f"VLM ready — frame shape {shape}, dtype {dtype}")
    return _vlm_instance, shape, dtype


def release_vlm():
    """Release VLM and VDevice resources. Safe to call multiple times."""
    global _vlm_instance, _vlm_vdevice
    if _vlm_instance is not None:
        try:
            _vlm_instance.clear_context()
            _vlm_instance.release()
        except Exception as e:
            logger.warning(f"Error releasing VLM: {e}")
        _vlm_instance = None
    if _vlm_vdevice is not None:
        try:
            _vlm_vdevice.release()
        except Exception as e:
            logger.warning(f"Error releasing VDevice: {e}")
        _vlm_vdevice = None


# --------------------------------------------------------------------------- #
#  hailo-ollama lifecycle helpers
# --------------------------------------------------------------------------- #
# The Hailo-10H NPU can only be held by one process at a time.  hailo-ollama
# (LLM server) keeps the device open, so we must stop it before loading the
# VLM and restart it afterwards.

def _stop_hailo_ollama() -> bool:
    """Stop all hailo-ollama processes. Returns True if any were killed."""
    try:
        result = subprocess.run(["pkill", "-f", "hailo-ollama serve"],
                                capture_output=True, timeout=5)
        if result.returncode == 0:
            # Give the NPU time to release
            time.sleep(1.5)
            logger.info("Stopped hailo-ollama to free NPU for VLM")
            return True
    except Exception as e:
        logger.warning(f"Failed to stop hailo-ollama: {e}")
    return False


def _start_hailo_ollama():
    """Restart hailo-ollama in the background."""
    try:
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "0.0.0.0:8000"
        subprocess.Popen(
            ["hailo-ollama", "serve"],
            stdout=open("/tmp/ollama.log", "a"),
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,     # detach from our process group
        )
        logger.info("Restarted hailo-ollama")
        # Wait for it to be ready before returning
        for _ in range(20):
            time.sleep(0.5)
            try:
                r = requests.get("http://127.0.0.1:8000/api/tags", timeout=2)
                if r.status_code == 200:
                    logger.info("hailo-ollama is ready")
                    return
            except requests.ConnectionError:
                pass
        logger.warning("hailo-ollama started but didn't become ready within 10s")
    except Exception as e:
        logger.error(f"Failed to restart hailo-ollama: {e}")


def _decode_image_to_frame(image_b64: str, target_shape, target_dtype=np.uint8):
    """Decode a base64 JPEG/PNG into a numpy array matching VLM input requirements.

    Uses a central-crop strategy (resize to cover + center crop) so the image
    is never stretched or distorted — matching the hailo-apps reference impl.
    """
    import cv2

    raw = base64.b64decode(image_b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image from base64 data")

    # OpenCV loads BGR; VLM expects RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    target_h, target_w = target_shape[0], target_shape[1]
    src_h, src_w = img.shape[:2]

    if src_h != target_h or src_w != target_w:
        # Scale to cover the target size, then center-crop (preserves aspect ratio)
        scale = max(target_w / src_w, target_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        x_start = (new_w - target_w) // 2
        y_start = (new_h - target_h) // 2
        img = img[y_start:y_start + target_h, x_start:x_start + target_w]

    return img.astype(target_dtype)

# Keep at most this many messages (plus the system prompt) to avoid
# unbounded memory growth on memory-constrained devices like a Pi.
MAX_HISTORY_MESSAGES = 20

_DISPLAY_IMAGE_KEYWORDS = [
    "show me a picture", "show me an image", "show me a photo",
    "show a picture", "show an image", "show a photo",
    "display a picture", "display an image", "display a photo",
    "picture of", "image of", "photo of",
    "generate an image", "generate a picture",
    "draw me", "draw a",
]

_MUSIC_KEYWORDS = [
    "play music", "play a song", "play me a song", "play some music",
    "sing a song", "sing me a song", "sing for me", "sing something",
    "play a tune", "play me a tune", "play some tunes",
    "can you sing", "will you sing", "do you sing",
    "play your music", "jam out", "dance for me",
    "sing for bmo", "bmo sing", "play me some music",
]

# Phrases that indicate the model is regurgitating system prompt instructions
_PROMPT_LEAK_PATTERNS = [
    re.compile(r'CRIT(?:IC)?AL:.*?JSON', re.IGNORECASE | re.DOTALL),
    re.compile(r'you MUST output.*?JSON', re.IGNORECASE | re.DOTALL),
    re.compile(r'output (?:exactly )?this JSON', re.IGNORECASE),
    re.compile(r'If the user asks.*?(?:output|JSON)', re.IGNORECASE | re.DOTALL),
    re.compile(r'Replace YOUR_PROMPT_HERE', re.IGNORECASE),
    re.compile(r'Valid emotions are:', re.IGNORECASE),
]


def _build_display_image_action(user_text: str) -> str:
    """Extract the subject from user text and return a display_image JSON action."""
    # Strip common prefixes to get the image subject
    subject = user_text
    for prefix in ["show me a picture of", "show me an image of", "show me a photo of",
                    "show a picture of", "show an image of", "show a photo of",
                    "display a picture of", "display an image of", "display a photo of",
                    "generate an image of", "generate a picture of",
                    "draw me a", "draw me an", "draw me", "draw a", "draw an",
                    "picture of", "image of", "photo of"]:
        lower = subject.lower()
        if lower.startswith(prefix):
            subject = subject[len(prefix):].strip()
            break
    # Remove trailing punctuation
    subject = subject.rstrip("?.!")
    prompt = urllib.parse.quote(subject.strip() or "something fun")
    return json.dumps({"action": "display_image", "image_url": f"https://image.pollinations.ai/prompt/{prompt}?width=512&height=512&nologo=true"})


def _strip_prompt_leakage(content: str) -> str:
    """Remove text that looks like the model echoing system prompt instructions."""
    for pat in _PROMPT_LEAK_PATTERNS:
        # Remove the matched pattern and everything after it (it's usually trailing noise)
        match = pat.search(content)
        if match:
            content = content[:match.start()].strip()
    return content


class Brain:
    def __init__(self):
        self.history = [{"role": "system", "content": get_system_prompt()}]

    def _trim_history(self):
        """Keep the system prompt + the most recent MAX_HISTORY_MESSAGES messages."""
        # history[0] is always the system prompt
        non_system = self.history[1:]
        if len(non_system) > MAX_HISTORY_MESSAGES:
            self.history = [self.history[0]] + non_system[-MAX_HISTORY_MESSAGES:]

    def think(self, user_text: str) -> str:
        """
        Send text to local LLM (Hailo/Ollama) and get response.
        """
        self.history.append({"role": "user", "content": user_text})

        lower_text = user_text.lower()

        # Pre-LLM camera check — same logic as stream_think
        camera_keywords = [
            "take a photo", "take a picture", "take photo", "take picture",
            "look at", "what do you see", "what can you see", "use your camera",
            "photograph", "snap a photo",
        ]
        if any(kw in lower_text for kw in camera_keywords):
            action = '{"action": "take_photo"}'
            self.history.append({"role": "assistant", "content": action})
            return action

        # Pre-LLM display_image check — handle image generation requests
        # directly instead of relying on the small model to emit correct JSON
        if any(kw in lower_text for kw in _DISPLAY_IMAGE_KEYWORDS):
            action = _build_display_image_action(user_text)
            matched_kw = next(kw for kw in _DISPLAY_IMAGE_KEYWORDS if kw in lower_text)
            bmo_print("LLM", f"Image keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            bmo_print("LLM", f"Emitting display_image action: {action[:80]}")
            self.history.append({"role": "assistant", "content": action})
            return action

        # Pre-LLM music check — emit play_music directly rather than
        # relying on the small model to emit correct JSON
        if any(kw in lower_text for kw in _MUSIC_KEYWORDS):
            action = '{"action": "play_music"}'
            matched_kw = next(kw for kw in _MUSIC_KEYWORDS if kw in lower_text)
            bmo_print("LLM", f"Music keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            bmo_print("LLM", "Emitting play_music action")
            self.history.append({"role": "assistant", "content": action})
            return action

        bmo_print("LLM", f"No pre-LLM action matched for: '{lower_text[:60]}'")

        # Pre-LLM web search — same logic as stream_think
        realtime_keywords = [
            "weather", "forecast", "temperature", "tonight", "tomorrow",
            "news", "latest", "right now", "score", "stocks", "bitcoin",
            "crypto", "price of", "happening", "recently", "live",
        ]
        question_markers = [
            "what", "who", "when", "where", "find", "search", "tell me",
            "look up", "check", "is there", "did", "?",
        ]
        has_realtime_kw = any(kw in lower_text for kw in realtime_keywords)
        has_question = any(q in lower_text for q in question_markers)
        search_injected = False
        if has_realtime_kw and has_question:
            try:
                search_result = search_web(user_text)
                if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR") and len(search_result) > 50:
                    # Strip the verbose "SEARCH RESULTS for '...':" header from search.py
                    clean_result = re.sub(r"^SEARCH RESULTS for '.*?':\n?", "", search_result).strip()
                    # Inject as a tight [LIVE DATA] block — clearer than the previous format
                    self.history[-1]["content"] = (
                        f"[LIVE DATA: {clean_result}] "
                        f"Using only the above live data, answer in one or two sentences as BMO: {user_text}"
                    )
                    search_injected = True
            except Exception as e:
                logger.warning(f"Pre-LLM web search failed: {e}")

        # Simple heuristic to route to a faster model for simple chat
        complex_keywords = ["explain", "story", "how", "why", "code", "write", "create", "analyze", "compare", "difference", "history", "long"]
        words = user_text.lower().split()
        
        chosen_model = FAST_LLM_MODEL
        if len(words) > 15 or any(kw in words for kw in complex_keywords):
            chosen_model = LLM_MODEL

        payload = {
            "model": chosen_model,
            "messages": self.history,
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": 180,  # increased to prevent responses getting cut off
            }
        }

        try:
            logger.info(f"Sending request to LLM ({chosen_model}): {LLM_URL}")
            response = requests.post(LLM_URL, json=payload, timeout=180)
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                
                # Check if the LLM outputted a JSON action (like search_web)
                try:
                    # Try to find JSON in the response (non-greedy)
                    # Also replace smart quotes with standard quotes before parsing
                    clean_content = content.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
                    json_match = re.search(r'\{.*?\}', clean_content, re.DOTALL)
                    if json_match:
                        action_data = json.loads(json_match.group(0))
                        
                        if action_data.get("action") == "take_photo":
                            logger.info("LLM requested to take a photo.")
                            # Return the JSON string directly so the caller can handle the camera
                            return json.dumps({"action": "take_photo"})
                            
                        elif action_data.get("action") == "search_web":
                            query = action_data.get("query", "")
                            logger.info(f"LLM requested web search for: {query}")
                            
                            # Perform the search
                            search_result = search_web(query)
                            
                            # Feed the result back to the LLM to summarize
                            summary_prompt = [
                                {"role": "system", "content": "Summarize this search result in one short, conversational sentence as BMO. Do not use markdown."},
                                {"role": "user", "content": f"RESULT: {search_result}\nUser Question: {user_text}"}
                            ]
                            
                            summary_payload = {
                                "model": FAST_LLM_MODEL,
                                "messages": summary_prompt,
                                "stream": False
                            }
                            
                            summary_response = requests.post(LLM_URL, json=summary_payload, timeout=180)
                            if summary_response.status_code == 200:
                                content = summary_response.json().get("message", {}).get("content", "")
                            else:
                                content = "I tried to search the web, but my brain got confused reading the results."
                except json.JSONDecodeError:
                    pass # Not valid JSON, just treat as normal text
                
                # Check for pronunciation learning tag
                pronounce_match = re.search(r'!PRONOUNCE:\s*([a-zA-Z0-9_-]+)\s*=\s*([a-zA-Z0-9_-]+)', content, re.IGNORECASE)
                if pronounce_match:
                    word = pronounce_match.group(1).strip()
                    phonetic = pronounce_match.group(2).strip()
                    logger.info(f"Learned new pronunciation from LLM: {word} -> {phonetic}")
                    add_pronunciation(word, phonetic)
                    # Remove the tag from the spoken content
                    content = re.sub(r'!PRONOUNCE:.*', '', content, flags=re.IGNORECASE).strip()

                # Strip any system prompt leakage from the response
                content = _strip_prompt_leakage(content)

                # Ensure BMO is spelled correctly in text responses
                content = re.sub(r'\bBeemo\b', 'BMO', content, flags=re.IGNORECASE)

                # Fallback if filtering left nothing useful
                if not content.strip():
                    content = "BMO is here! How can I help?"

                self.history.append({"role": "assistant", "content": content})

                # Clean injected search context from history so it doesn't
                # accumulate and confuse the model on future turns.
                if search_injected:
                    for msg in reversed(self.history):
                        if msg.get("role") == "user" and msg.get("content", "").startswith("[LIVE DATA:"):
                            msg["content"] = user_text
                            break

                self._trim_history()
                return content

            else:
                logger.error(f"LLM Error: {response.status_code} - {response.text}")
                return f"Error: {response.status_code}"
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error to {LLM_URL}: {e}")
            return "Could not connect to my brain. Is the Hailo server running?"
        except Exception as e:
            logger.error(f"Brain Exception: {e}")
            return "I'm having trouble thinking right now."

    def get_history(self):
        return self.history

    def stream_think(self, user_text: str):
        """
        Send text to local LLM and yield full sentences as they are generated.
        Useful for TTS chunking (speaking while generating).
        """
        self.history.append({"role": "user", "content": user_text})

        lower_text = user_text.lower()

        # Pre-LLM camera check: if user asks to take a photo / look at something,
        # emit the action JSON directly without calling the LLM.
        # This is more reliable than hoping the small model emits the right JSON.
        camera_keywords = [
            "take a photo", "take a picture", "take photo", "take picture",
            "look at", "what do you see", "what can you see", "use your camera",
            "photograph", "snap a photo",
        ]
        if any(kw in lower_text for kw in camera_keywords):
            action = '{"action": "take_photo"}'
            self.history.append({"role": "assistant", "content": action})
            yield action
            return

        # Pre-LLM display_image check
        if any(kw in lower_text for kw in _DISPLAY_IMAGE_KEYWORDS):
            action = _build_display_image_action(user_text)
            matched_kw = next(kw for kw in _DISPLAY_IMAGE_KEYWORDS if kw in lower_text)
            bmo_print("LLM-STREAM", f"Image keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            self.history.append({"role": "assistant", "content": action})
            yield action
            return

        # Pre-LLM music check — emit play_music directly
        if any(kw in lower_text for kw in _MUSIC_KEYWORDS):
            action = '{"action": "play_music"}'
            matched_kw = next(kw for kw in _MUSIC_KEYWORDS if kw in lower_text)
            bmo_print("LLM-STREAM", f"Music keyword MATCHED: '{matched_kw}' in '{lower_text[:60]}'")
            self.history.append({"role": "assistant", "content": action})
            yield action
            return

        bmo_print("LLM-STREAM", f"No pre-LLM action matched for: '{lower_text[:60]}'")

        # Pre-LLM keyword check: if the question likely needs real-time info,
        # do the web search now rather than relying on the model to emit JSON.
        # Require at least one realtime keyword AND the text to look like a question
        # (contains 'what', 'who', 'when', 'find', 'search', '?', etc.) to avoid
        # false triggers on casual phrases like 'how are you doing today'.
        realtime_keywords = [
            "weather", "forecast", "temperature", "tonight", "tomorrow",
            "news", "latest", "right now", "score", "stocks", "bitcoin",
            "crypto", "price of", "happening", "recently", "live",
        ]
        question_markers = [
            "what", "who", "when", "where", "find", "search", "tell me",
            "look up", "check", "is there", "did", "?",
        ]
        has_realtime_kw = any(kw in lower_text for kw in realtime_keywords)
        has_question = any(q in lower_text for q in question_markers)
        needs_search = has_realtime_kw and has_question
        search_injected = False
        if needs_search:
            try:
                search_result = search_web(user_text)
                # Only inject if we got a real result (not empty/error sentinel)
                if search_result and search_result not in ("SEARCH_EMPTY", "SEARCH_ERROR") and len(search_result) > 50:
                    # Strip verbose "SEARCH RESULTS for '...':" prefix from search.py
                    clean_result = re.sub(r"^SEARCH RESULTS for '.*?':\n?", "", search_result).strip()
                    self.history[-1]["content"] = (
                        f"[LIVE DATA: {clean_result}] "
                        f"Using only the above live data, answer in one or two sentences as BMO: {user_text}"
                    )
                    search_injected = True
            except Exception as e:
                logger.warning(f"Pre-LLM web search failed: {e}")

        # Simple heuristic to route to a faster model for simple chat
        complex_keywords = ["explain", "story", "how", "why", "code", "write", "create", "analyze", "compare", "difference", "history", "long"]
        words = user_text.lower().split()
        
        chosen_model = FAST_LLM_MODEL
        if len(words) > 15 or any(kw in words for kw in complex_keywords):
            chosen_model = LLM_MODEL



        payload = {
            "model": chosen_model,
            "messages": self.history,
            "stream": True,
            "options": {
                "temperature": 0.4,
                "num_predict": 180,  # increased to prevent responses getting cut off
            }
        }

        full_content = ""
        buffer = ""
        
        try:
            logger.info(f"Stream request to LLM ({chosen_model}): {LLM_URL}")
            with requests.post(LLM_URL, json=payload, stream=True, timeout=180) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("message", {}).get("content", "")
                                if not chunk:
                                    continue
                                    
                                # Replace smart quotes
                                chunk = chunk.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
                                
                                buffer += chunk
                                full_content += chunk
                                
                                # If buffer ends with punctuation or newline, yield it
                                if any(buffer.endswith(punc) for punc in ['.', '!', '?', '\n']) or "\n\n" in buffer:
                                    # Strip system prompt leakage
                                    cleaned = _strip_prompt_leakage(buffer)
                                    # Ensure BMO spelling before yielding
                                    out_chunk = re.sub(r'\bBeemo\b', 'BMO', cleaned, flags=re.IGNORECASE)
                                    if out_chunk.strip():
                                        yield out_chunk
                                    buffer = ""
                                    
                            except json.JSONDecodeError:
                                pass
                                
                    # Yield any remaining buffer
                    if buffer.strip():
                        cleaned = _strip_prompt_leakage(buffer)
                        out_chunk = re.sub(r'\bBeemo\b', 'BMO', cleaned, flags=re.IGNORECASE)
                        if out_chunk.strip():
                            yield out_chunk
                        
                    # Handle json actions at the very end if applicable
                    json_match = re.search(r'\{.*?\}', full_content, re.DOTALL)
                    if json_match and "action" in json_match.group(0):
                        # For advanced tool use we won't yield the json action to TTS
                        pass 
                    
                    self.history.append({"role": "assistant", "content": full_content})

                    # Clean injected search context from history so it doesn't
                    # accumulate and confuse the model on future turns.
                    if search_injected:
                        for msg in reversed(self.history):
                            if msg.get("role") == "user" and msg.get("content", "").startswith("[LIVE DATA:"):
                                msg["content"] = user_text
                                break

                    self._trim_history()

                else:
                    logger.error(f"LLM Stream Error: {response.status_code} - {response.text}")
                    yield "I'm having trouble thinking."
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error to {LLM_URL}: {e}")
            yield "Could not connect to my brain."
        except Exception as e:
            logger.error(f"Brain Exception: {e}")
            yield "I'm having trouble right now."

    def set_history(self, new_history):
        # Ensure system prompt is always present and up to date
        if not new_history or new_history[0].get("role") != "system":
            new_history.insert(0, {"role": "system", "content": get_system_prompt()})
        else:
            new_history[0]["content"] = get_system_prompt()
        self.history = new_history

    def analyze_image(self, image_base64: str, user_text: str) -> str:
        """
        Analyse an image using the Hailo VLM (Qwen2-VL-2B) running directly
        on the NPU via the HailoRT Python API.  Falls back to a polite error
        message if the HEF isn't available or the hardware can't be reached.
        """
        # Strip data URI prefix if present (browser sends "data:image/jpeg;base64,...")
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]

        # We don't append the image to the main history to save context window,
        # but we do append the user's question and the assistant's answer.
        self.history.append({"role": "user", "content": user_text})

        # Stop hailo-ollama so the NPU is free for VLM
        ollama_was_running = _stop_hailo_ollama()

        try:
            vlm, frame_shape, frame_dtype = _get_vlm()

            # Decode the base64 image into a numpy frame the VLM expects
            frame = _decode_image_to_frame(image_base64, frame_shape, frame_dtype)

            # Build the structured prompt expected by the Qwen2-VL model
            prompt = [
                {"role": "system", "content": [
                    {"type": "text", "text": "You are BMO, a helpful robot assistant. Describe what you see concisely and conversationally in English."}
                ]},
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": user_text or "What do you see in this image?"}
                ]}
            ]

            logger.info("Running VLM inference on Hailo NPU ...")
            vlm.clear_context()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    vlm.generate_all,
                    prompt=prompt,
                    frames=[frame],
                    max_generated_tokens=200,
                    temperature=0.4,
                    seed=42,
                )
                try:
                    content = future.result(timeout=60)
                except concurrent.futures.TimeoutError:
                    logger.warning("VLM inference timed out after 60 seconds")
                    vlm.clear_context()
                    return "BMO looked too long and got dizzy! Try again?"

            # Clean up any smart quotes, stop tokens, or stray formatting
            content = content.replace('\u201c', '"').replace('\u201d', '"')
            content = content.replace('\u2018', "'").replace('\u2019', "'")
            for tok in ("<|im_end|>", "<|endoftext|>", "<|im_start|>"):
                content = content.replace(tok, "")
            content = content.strip()

            logger.info(f"VLM response ({len(content)} chars): {content[:120]}...")

            self.history.append({"role": "assistant", "content": content})
            return content

        except FileNotFoundError as e:
            logger.warning(f"VLM HEF not found: {e}")
            return "BMO's vision model isn't installed yet. Run setup.sh to download it!"
        except Exception as e:
            logger.error(f"VLM Exception: {e}", exc_info=True)
            # Ensure VLM context is clean for the next call
            try:
                if _vlm_instance is not None:
                    _vlm_instance.clear_context()
            except Exception:
                pass
            return "I tried to look, but my eyes aren't working right now."
        finally:
            # Release VLM so the NPU is free, then restart hailo-ollama
            release_vlm()
            if ollama_was_running:
                _start_hailo_ollama()
