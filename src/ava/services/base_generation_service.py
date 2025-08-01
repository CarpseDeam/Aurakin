# src/ava/services/base_generation_service.py
import re
from typing import Any, Optional, AsyncGenerator

from src.ava.core.event_bus import EventBus


class BaseGenerationService:
    """A base class for generation services providing common utilities."""

    def __init__(self, service_manager: Any, event_bus: EventBus):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = service_manager.get_llm_client()
        self.project_manager = service_manager.get_project_manager()

    def log(self, level: str, message: str, **kwargs):
        """Helper to emit log messages."""
        self.event_bus.emit("log_message_received", self.__class__.__name__, level, message, **kwargs)

    async def _call_llm_agent(self, prompt: str, role: str, max_tokens: Optional[int] = None) -> Optional[str]:
        """
        Calls an LLM agent and accumulates the entire response into a single string.
        Used for tasks that require the full response at once (e.g., planning).
        """
        response_content = ""
        try:
            # Use the new streaming generator and accumulate the results
            async for chunk in self._stream_llm_agent_chunks(prompt, role, max_tokens=max_tokens):
                response_content += chunk

            # Check for our specific error token at the end of accumulation.
            if response_content.startswith("LLM_API_ERROR:"):
                self.log("error", f"API Error from LLM for role '{role}': {response_content}")
                return None
            return response_content
        except Exception as e:
            self.log("error", f"Error during LLM call accumulation for role '{role}': {e}", exc_info=True)
            return None

    async def _stream_llm_agent_chunks(self, prompt: str, role: str, max_tokens: Optional[int] = None) -> AsyncGenerator[str, None]:
        """
        Calls an LLM agent and yields response chunks as they arrive.
        Used for real-time streaming of code generation.
        """
        provider, model = self.llm_client.get_model_for_role(role)
        if not provider or not model:
            self.log("error", f"No model configured for role '{role}'")
            yield f"LLM_API_ERROR: No model configured for role '{role}'"
            return

        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, role, max_tokens=max_tokens):
                # Immediately yield each chunk as it comes in.
                yield chunk
        except Exception as e:
            self.log("error", f"Error streaming from LLM for role '{role}': {e}", exc_info=True)
            yield f"LLM_API_ERROR: {e}"