import os
import google.generativeai as genai
from .llm_interface import LLMProvider

class GeminiAdapter(LLMProvider):
    def __init__(self, api_key=None, model_name="gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set. Please set it in your environment.")
        
        genai.configure(api_key=self.api_key)
        self.model_name = model_name
        
        # Safety settings: We block minimal content to avoid code generation issues
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        try:
            model = genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
            response = model.generate_content(
                prompt, 
                safety_settings=self.safety_settings
            )
            return response.text
        except Exception as e:
            print(f"🚨 Gemini Generate Error: {e}")
            return ""

    def chat(self, messages: List[Dict[str, str]], system_instruction: str = None) -> str:
        try:
            model = genai.GenerativeModel(self.model_name, system_instruction=system_instruction)
            
            # 1. Convert OpenAI-style messages to Gemini history format
            gemini_history = []
            last_user_msg = ""
            
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                content = msg["content"]
                
                # Gemini's chat.send_message expects the *new* message separate from history
                if msg == messages[-1] and msg["role"] == "user":
                    last_user_msg = content
                else:
                    gemini_history.append({"role": role, "parts": [content]})

            # 2. Start Chat Session
            chat = model.start_chat(history=gemini_history)
            
            # 3. Send Message
            response = chat.send_message(last_user_msg, safety_settings=self.safety_settings)
            return response.text
            
        except Exception as e:
            print(f"🚨 Gemini Chat Error: {e}")
            return ""