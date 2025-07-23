# src/ava/services/scaffolding_service.py
import asyncio
from typing import Dict, Any, Optional

from src.ava.core.event_bus import EventBus
from src.ava.prompts import ARCHITECT_SCAFFOLD_PROMPT
from src.ava.services.base_generation_service import BaseGenerationService
from src.ava.services.response_validator_service import ResponseValidatorService


class ScaffoldingService(BaseGenerationService):
    """Phase 1: Architect builds the project skeleton."""

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.validator = ResponseValidatorService()

    async def execute(self, user_request: str) -> Optional[Dict[str, str]]:
        """
        Executes the scaffolding phase of generation.
        """
        self.log("info", "--- Phase 1: Architect is building the project skeleton... ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Designing project skeleton...", "fa5s.drafting-compass")

        prompt = ARCHITECT_SCAFFOLD_PROMPT.format(user_request=user_request)
        raw_response = await self._call_llm_agent(prompt, "architect")

        if not raw_response:
            self.log("error", "Architect returned an empty response.")
            return None

        parsed_json = self.validator.extract_and_parse_json(raw_response)
        if not parsed_json:
            self.log("error", f"Validator could not extract valid JSON from Architect's response. Response: {raw_response[:500]}")
            return None

        scaffold_files = self.validator.validate_and_flatten_scaffold(parsed_json)
        if not scaffold_files:
            self.log("error", "Validator could not process the parsed JSON into a valid scaffold structure.")
            return None

        self.event_bus.emit("project_scaffold_generated", scaffold_files)
        await asyncio.sleep(0.5)
        return scaffold_files