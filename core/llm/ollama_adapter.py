import requests
import os
from .llm_interface import LLMProvider

class OllamaAdapter(LLMProvider):
    def __init__(self, base_url=None, model_name="llama3:8b"):
        # Default to localhost, but allow env var to point to your server (e.g., http://192.168.1.50:11434)
        self.base_url = base_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model_name = model_name

    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        full_prompt = prompt
        # Ollama raw mode often handles system prompts better when prepended
        if system_instruction:
            full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.2, # Low temp for code accuracy
                "num_ctx": 8192     # Larger context window for analyzing code
            }
        }
        
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            print(f"🚨 Ollama Connection Error ({self.base_url}): {e}")
            return ""

    def chat(self, messages: list, system_instruction: str = None) -> str:
        # Prepend system instruction if it exists
        chat_messages = list(messages) # Copy to avoid modifying original
        if system_instruction:
            chat_messages.insert(0, {"role": "system", "content": system_instruction})

        payload = {
            "model": self.model_name,
            "messages": chat_messages,
            "stream": False,
             "options": {
                "temperature": 0.2
            }
        }

        try:
            response = requests.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")
        except Exception as e:
            print(f"🚨 Ollama Chat Error: {e}")
            return ""