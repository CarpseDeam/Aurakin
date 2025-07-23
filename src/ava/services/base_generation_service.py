# src/ava/services/base_generation_service.py
import re
from typing import Any, Optional

from src.ava.core.event_bus import EventBus


class BaseGenerationService:
    """A base class for generation services providing common utilities."""

    def __init__(self, service_manager: Any, event_bus: EventBus):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = service_manager.get_llm_client()

    def log(self, level: str, message: str, **kwargs):
        """Helper to emit log messages."""
        self.event_bus.emit("log_message_received", self.__class__.__name__, level, message, **kwargs)

    async def _call_llm_agent(self, prompt: str, role: str) -> Optional[str]:
        """Generic LLM call helper."""
        provider, model = self.llm_client.get_model_for_role(role)
        if not provider or not model:
            self.log("error", f"No model configured for role '{role}'")
            return None

        response_content = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, role):
                response_content += chunk

            # Coder role often wraps code in markdown blocks
            if role == "coder":
                match = re.search(r"```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```", response_content, re.DOTALL)
                return match.group(1).strip() if match else response_content.strip()
            return response_content
        except Exception as e:
            self.log("error", f"Error from LLM for role '{role}': {e}", exc_info=True)
            return None