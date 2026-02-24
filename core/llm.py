import requests
import logging
import re
import json
from .config import LLM_URL, LLM_MODEL, VISION_MODEL, SYSTEM_PROMPT
from .tts import add_pronunciation
from .search import search_web

logger = logging.getLogger(__name__)

class Brain:
    def __init__(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def think(self, user_text: str) -> str:
        """
        Send text to local LLM (Hailo/Ollama) and get response.
        """
        self.history.append({"role": "user", "content": user_text})

        payload = {
            "model": LLM_MODEL,
            "messages": self.history,
            "stream": False
        }

        try:
            logger.info(f"Sending request to LLM: {LLM_URL}")
            response = requests.post(LLM_URL, json=payload, timeout=60)
            
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
                                "model": LLM_MODEL,
                                "messages": summary_prompt,
                                "stream": False
                            }
                            
                            summary_response = requests.post(LLM_URL, json=summary_payload, timeout=60)
                            if summary_response.status_code == 200:
                                content = summary_response.json().get("message", {}).get("content", "")
                            else:
                                content = "I tried to search the web, but my brain got confused reading the results."
                except json.JSONDecodeError:
                    pass # Not valid JSON, just treat as normal text
                
                # Check for pronunciation learning tag
                pronounce_match = re.search(r'!PRONOUNCE:\s*([a-zA-Z0-9_-]+)\s*=\s*([a-zA-Z0-9_-]+)', content)
                if pronounce_match:
                    word = pronounce_match.group(1).strip()
                    phonetic = pronounce_match.group(2).strip()
                    logger.info(f"Learned new pronunciation from LLM: {word} -> {phonetic}")
                    add_pronunciation(word, phonetic)
                    # Remove the tag from the spoken content
                    content = re.sub(r'!PRONOUNCE:.*', '', content).strip()

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

    def get_history(self):
        return self.history

    def set_history(self, new_history):
        # Ensure system prompt is always present
        if not new_history or new_history[0].get("role") != "system":
            new_history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
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
