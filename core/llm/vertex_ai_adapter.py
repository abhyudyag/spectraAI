import os
import vertexai
from vertexai.generative_models import GenerativeModel, SafetySetting
from .llm_interface import LLMProvider

class VertexAIAdapter(LLMProvider):
    def __init__(self, project_id=None, location="us-central1", model_name="gemini-1.5-flash-001"):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.location = location or os.getenv("GCP_LOCATION", "us-central1")
        
        # Initialize Vertex AI SDK
        vertexai.init(project=self.project_id, location=self.location)
        self.model_name = model_name
        
        # Enterprise-grade safety settings (configurable)
        self.safety_settings = [
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH
            ),
             SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH
            ),
             SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH
            )
        ]

    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        try:
            model = GenerativeModel(self.model_name, system_instruction=[system_instruction] if system_instruction else None)
            response = model.generate_content(
                prompt,
                safety_settings=self.safety_settings
            )
            return response.text
        except Exception as e:
            print(f"🚨 Vertex AI Error: {e}")
            return ""

    def chat(self, messages: list, system_instruction: str = None) -> str:
        try:
            model = GenerativeModel(self.model_name, system_instruction=[system_instruction] if system_instruction else None)
            
            # Convert messages to Vertex AI History format
            history = []
            last_msg = ""
            
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                if msg == messages[-1] and msg["role"] == "user":
                    last_msg = msg["content"]
                else:
                    history.append({"role": role, "parts": [msg["content"]]})

            chat = model.start_chat(history=history)
            response = chat.send_message(last_msg, safety_settings=self.safety_settings)
            return response.text
        except Exception as e:
            print(f"🚨 Vertex AI Chat Error: {e}")
            return ""