import requests
import logging
import re
import json
import google.generativeai as genai
from .config import LLM_URL, LLM_MODEL, FAST_LLM_MODEL, VISION_MODEL, get_system_prompt, GEMINI_API_KEY, GEMINI_MODEL
from .tts import add_pronunciation
from .search import search_web

logger = logging.getLogger(__name__)

class Brain:
    def __init__(self):
        self.history = [{"role": "system", "content": get_system_prompt()}]
        self.gemini_configured = False
        if GEMINI_API_KEY:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                self.gemini_configured = True
            except Exception as e:
                logger.error(f"Failed to configure Gemini: {e}")

    def think(self, user_text: str) -> str:
        """
        Send text to local LLM (Hailo/Ollama) and get response.
        """
        self.history.append({"role": "user", "content": user_text})

        # Check for Gemini trigger
        trigger_words = ["hey gemini", "gemini", "bmo gemini", "bmo gem"]
        is_gemini_request = False
        lower_text = user_text.lower().strip()
        
        if self.gemini_configured:
            for trigger in trigger_words:
                if lower_text.startswith(trigger):
                    is_gemini_request = True
                    # Strip the trigger from the actual prompt sent to the LLM
                    user_text = re.sub(f"^{trigger}[,\\s]*", "", user_text, flags=re.IGNORECASE).strip()
                    break

        if is_gemini_request:
            return self._think_gemini(user_text)

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
                "temperature": 0.4
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

    def _think_gemini(self, user_text: str) -> str:
        """Helper to process requests via Gemini API."""
        try:
            logger.info(f"Sending request to Gemini ({GEMINI_MODEL})")
            
            # Convert history to Gemini format
            gemini_messages = []
            
            # System prompt needs to be passed in model generation config or prepended
            system_instruction = get_system_prompt()
            
            for msg in self.history:
                if msg["role"] == "system":
                    continue # Skip system msgs here, handled below
                    
                role = "user" if msg["role"] == "user" else "model"
                gemini_messages.append({"role": role, "parts": [msg["content"]]})
                
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_instruction
            )
            
            response = model.generate_content(gemini_messages)
            content = response.text
            
            # Same parsing logic for JSON actions
            try:
                clean_content = content.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
                json_match = re.search(r'\{.*?\}', clean_content, re.DOTALL)
                if json_match:
                    action_data = json.loads(json_match.group(0))
                    if action_data.get("action") == "take_photo":
                        return json.dumps({"action": "take_photo"})
                    elif action_data.get("action") == "search_web":
                        query = action_data.get("query", "")
                        search_result = search_web(query)
                        # We won't re-summarize with Gemini to keep it simple, just add to history and run again
                        self.history.append({"role": "assistant", "content": content})
                        self.history.append({"role": "user", "content": f"Search results for '{query}': {search_result}. Please summarize."})
                        return self._think_gemini("Please summarize the search results.")
            except Exception:
                pass
                
            # Formatting
            content = re.sub(r'!PRONOUNCE:.*', '', content, flags=re.IGNORECASE).strip()
            content = re.sub(r'\bBeemo\b', 'BMO', content, flags=re.IGNORECASE)
            
            self.history.append({"role": "assistant", "content": content})
            return content
            
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            return "I tried to ask Gemini, but there was a connection error."

    def get_history(self):
        return self.history

    def stream_think(self, user_text: str):
        """
        Send text to local LLM and yield full sentences as they are generated.
        Useful for TTS chunking (speaking while generating).
        """
        self.history.append({"role": "user", "content": user_text})

        # Check for Gemini trigger
        trigger_words = ["hey gemini", "gemini", "bmo gemini", "bmo gem"]
        is_gemini_request = False
        lower_text = user_text.lower().strip()
        
        if self.gemini_configured:
            for trigger in trigger_words:
                if lower_text.startswith(trigger):
                    is_gemini_request = True
                    user_text = re.sub(f"^{trigger}[,\\s]*", "", user_text, flags=re.IGNORECASE).strip()
                    break

        if is_gemini_request:
            # yield from delegates the generator
            yield from self._stream_think_gemini(user_text)
            return

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
                "temperature": 0.4
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
                        
                else:
                    logger.error(f"LLM Stream Error: {response.status_code} - {response.text}")
                    yield "I'm having trouble thinking."
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection Error: {e}")
            yield "Could not connect to my brain."
        except Exception as e:
            logger.error(f"Brain Exception: {e}")
            yield "I'm having trouble right now."

    def _stream_think_gemini(self, user_text: str):
        """Helper to stream requests via Gemini API."""
        try:
            logger.info(f"Stream request to Gemini ({GEMINI_MODEL})")
            
            gemini_messages = []
            system_instruction = get_system_prompt()
            
            for msg in self.history:
                if msg["role"] == "system":
                    continue
                role = "user" if msg["role"] == "user" else "model"
                gemini_messages.append({"role": role, "parts": [msg["content"]]})
                
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_instruction
            )
            
            # Using stream=True with google-generativeai
            response = model.generate_content(gemini_messages, stream=True)
            
            full_content = ""
            buffer = ""
            
            for chunk in response:
                if chunk.text:
                    text_chunk = chunk.text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
                    buffer += text_chunk
                    full_content += text_chunk
                    
                    if any(buffer.endswith(punc) for punc in ['.', '!', '?', '\n']) or "\n\n" in buffer:
                        out_chunk = re.sub(r'\bBeemo\b', 'BMO', buffer, flags=re.IGNORECASE)
                        yield out_chunk
                        buffer = ""
                        
            if buffer.strip():
                out_chunk = re.sub(r'\bBeemo\b', 'BMO', buffer, flags=re.IGNORECASE)
                yield out_chunk
                
            self.history.append({"role": "assistant", "content": full_content})
            
        except Exception as e:
            logger.error(f"Gemini API Stream Error: {e}")
            yield "I tried to ask Gemini, but there was a connection error."

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
