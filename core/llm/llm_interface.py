from abc import ABC, abstractmethod
from typing import List, Dict, Any

class LLMProvider(ABC):
    """
    Abstract Base Class for LLM Providers.
    Enforces a strict contract for any brain we plug into Spectra.
    """

    @abstractmethod
    def generate_content(self, prompt: str, system_instruction: str = None) -> str:
        """
        Generates text based on a single prompt.
        """
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], system_instruction: str = None) -> str:
        """
        Handles a conversation history.
        messages: List of {"role": "user/assistant", "content": "..."}
        """
        pass