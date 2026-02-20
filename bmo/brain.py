from . import config
import time
import requests
import json
import logging

class Brain:
    def __init__(self, ui_controller):
        self.ui = ui_controller
        self.history = [{"role": "system", "content": "You are BMO, a helpful robot assistant. Keep answers short and fun."}]

    def think(self, user_text):
        """
        Send text to local LLM (Hailo/Ollama) and get response.
        """
        self.ui.set_state("thinking", "Hmm...")
        self.history.append({"role": "user", "content": user_text})

        payload = {
            "model": config.LLM_MODEL,
            "messages": self.history,
            "stream": False
        }

        try:
            # Direct HTTP call to localhost:8000
            response = requests.post(config.LLM_URL, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                self.history.append({"role": "assistant", "content": content})
                return content
            else:
                logging.error(f"LLM Error: {response.status_code} - {response.text}")
                return "My brain hurts."
        except Exception as e:
            logging.error(f"Brain Exception: {e}")
            return "I can't think right now."
