import requests
import logging
import re
from .config import LLM_URL, LLM_MODEL, SYSTEM_PROMPT
from .tts import add_pronunciation

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
