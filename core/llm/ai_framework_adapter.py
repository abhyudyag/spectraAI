import os
from .google_gemini_adapter import GeminiAdapter
from .ollama_adapter import OllamaAdapter

# Simple wrapper to match your existing code's expected response format (response.text)
class AIResponse:
    def __init__(self, text):
        self.text = text

class AIFrameworkAdapter:
    def __init__(self):
        # Configuration Strategy:
        
        self.provider_type = os.getenv("SPECTRA_LLM_PROVIDER", "").lower()
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.provider_type = os.getenv("SPECTRA_LLM_PROVIDER", "vertex").lower()
        
        if self.provider_type == "vertex":
             from .vertex_ai_adapter import VertexAIAdapter
             print("🧠 Brain: Google Vertex AI (GCP Native)")
             self.client = VertexAIAdapter(
                 project_id=os.getenv("GCP_PROJECT_ID"),
                 model_name=os.getenv("VERTEX_MODEL", "gemini-1.5-flash-001")
             )
        
        # Auto-detect logic if not explicitly set
        if not self.provider_type:
            if self.gemini_key:
                self.provider_type = "gemini"
            else:
                self.provider_type = "ollama"

        # Initialize the chosen provider
        if self.provider_type == "gemini":
            print("🧠 Brain: Google Gemini (Cloud)")
            self.client = GeminiAdapter(
                api_key=self.gemini_key,
                model_name=os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
            )
        else:
            host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            print(f"🧠 Brain: Ollama (Local/Server) [{host}]")
            self.client = OllamaAdapter(
                base_url=host,
                model_name=os.getenv("OLLAMA_MODEL", "llama3:8b")
            )

    def generate_content(self, prompt, system_instruction=None):
        """Standardized method called by Agents."""
        text_response = self.client.generate_content(prompt, system_instruction)
        return AIResponse(text_response)

    def chat(self, messages, system_instruction=None):
        text_response = self.client.chat(messages, system_instruction)
        return AIResponse(text_response)