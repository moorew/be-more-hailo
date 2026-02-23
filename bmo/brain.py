from core.llm import Brain as CoreBrain
import logging

class Brain:
    def __init__(self, ui_controller):
        self.ui = ui_controller
        self.core_brain = CoreBrain()

    def think(self, user_text):
        """
        Send text to local LLM (Hailo/Ollama) and get response.
        """
        self.ui.set_state("thinking", "Hmm...")
        
        # Use the unified core brain
        content = self.core_brain.think(user_text)
        
        # The core brain handles errors by returning strings starting with "Error:" etc.
        if content.startswith("Error:") or content.startswith("Could not connect") or content.startswith("I'm having trouble"):
            logging.error(f"Brain Error: {content}")
            return "My brain hurts."
            
        return content
