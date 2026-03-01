import requests
import logging
import re
import json
from .config import LLM_URL, LLM_MODEL, FAST_LLM_MODEL, VISION_MODEL, get_system_prompt
from .tts import add_pronunciation
from .search import search_web

logger = logging.getLogger(__name__)

class Brain:
    def __init__(self):
        self.history = [{"role": "system", "content": get_system_prompt()}]

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
                "num_predict": 120,  # cap tokens to prevent runaway verbosity
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

                # Ensure BMO is spelled correctly in text responses
                content = re.sub(r'\bBeemo\b', 'BMO', content, flags=re.IGNORECASE)

                self.history.append({"role": "assistant", "content": content})

                # Clean injected search context from history so it doesn't
                # accumulate and confuse the model on future turns.
                if search_injected:
                    for msg in reversed(self.history):
                        if msg.get("role") == "user" and msg.get("content", "").startswith("[LIVE DATA:"):
                            msg["content"] = user_text
                            break

                return content

            else:
                logger.error(f"LLM Error: {response.status_code} - {response.text}")
                return f"Error: {response.status_code}"
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error: {e}")
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
                "num_predict": 120,  # cap tokens to prevent runaway verbosity
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
                                    # Ensure BMO spelling before yielding
                                    out_chunk = re.sub(r'\bBeemo\b', 'BMO', buffer, flags=re.IGNORECASE)
                                    yield out_chunk
                                    buffer = ""
                                    
                            except json.JSONDecodeError:
                                pass
                                
                    # Yield any remaining buffer
                    if buffer.strip():
                        out_chunk = re.sub(r'\bBeemo\b', 'BMO', buffer, flags=re.IGNORECASE)
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
                        

                else:
                    logger.error(f"LLM Stream Error: {response.status_code} - {response.text}")
                    yield "I'm having trouble thinking."
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error: {e}")
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
        Send an image and text to the vision model (e.g., moondream) and get a response.
        """
        # Strip data URI prefix if present
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
            
        # We don't append the image to the main history to save context window,
        # but we do append the user's question and the assistant's answer.
        self.history.append({"role": "user", "content": user_text})
        
        # Create a temporary message list for the vision model
        vision_messages = [
            {"role": "system", "content": "You are BMO, a helpful robot assistant. Describe what you see in the image concisely and conversationally."},
            {
                "role": "user",
                "content": user_text,
                "images": [image_base64]
            }
        ]
        
        payload = {
            "model": VISION_MODEL,
            "messages": vision_messages,
            "stream": False
        }
        
        try:
            logger.info(f"Sending image to Vision Model ({VISION_MODEL}) at {LLM_URL}")
            response = requests.post(LLM_URL, json=payload, timeout=120) # Vision takes longer
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                
                # Clean up any markdown or weird formatting
                content = content.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
                
                self.history.append({"role": "assistant", "content": content})
                return content
            else:
                logger.error(f"Vision Model Error: {response.status_code} - {response.text}")
                return "I tried to look, but my eyes aren't working right now."
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Vision Connection Error: {e}")
            return "I couldn't connect to my vision processor."
        except Exception as e:
            logger.error(f"Vision Exception: {e}")
            return "I'm having trouble seeing right now."
