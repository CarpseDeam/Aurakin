# src/ava/services/test_generation_service.py
from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Any, Dict
import re

from src.ava.prompts import TESTER_PROMPT, FILE_TESTER_PROMPT
from src.ava.prompts.master_rules import S_TIER_ENGINEERING_PROTOCOL, RAW_CODE_OUTPUT_RULE
from src.ava.services.base_generation_service import BaseGenerationService
from src.ava.utils import sanitize_llm_code_output

if TYPE_CHECKING:
    from src.ava.core.event_bus import EventBus


class TestGenerationService(BaseGenerationService):
    """
    A specialized service to handle the generation of unit tests for functions or entire files.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.log("info", "TestGenerationService Initialized.")

    async def generate_test_for_function(self, function_name: str, function_code: str, source_file_path: str) -> \
    Optional[Dict[str, str]]:
        """
        Generates assets (test file, requirements) for a given function.
        """
        self.log("info", f"Generating unit test for function '{function_name}' from '{source_file_path}'.")
        self.event_bus.emit("agent_status_changed", "Tester", f"Generating test for {function_name}", "fa5s.vial")

        module_path = source_file_path.replace('/', '.').replace('\\\\', '.').removesuffix('.py')

        prompt = TESTER_PROMPT.format(
            function_name=function_name,
            function_code=function_code,
            module_path=module_path,
            S_TIER_ENGINEERING_PROTOCOL=S_TIER_ENGINEERING_PROTOCOL,
            RAW_CODE_OUTPUT_RULE=RAW_CODE_OUTPUT_RULE
        )

        full_response = await self._call_llm_agent(prompt, "tester")

        if not full_response:
            self.log("error", f"Tester agent failed to generate content for function '{function_name}'.")
            return None

        parts = full_response.split("---requirements.txt---")
        test_code = sanitize_llm_code_output(parts)

        requirements_content = None
        if len(parts) > 1:
            requirements_content = parts.strip()

        self.log("success", f"Successfully generated test content for '{function_name}'.")
        return {"test_code": test_code, "requirements": requirements_content}

    async def generate_tests_for_file(self, file_content: str, source_file_path: str) -> Optional[Dict[str, str]]:
        """
        Generates a comprehensive test file for all public members of a given source file.
        """
        self.log("info", f"Generating comprehensive unit tests for file '{source_file_path}'.")
        self.event_bus.emit("agent_status_changed", "Tester", f"Testing {source_file_path}", "fa5s.vial")

        module_path = source_file_path.replace('/', '.').replace('\\\\', '.').removesuffix('.py')

        prompt = FILE_TESTER_PROMPT.format(
            file_content=file_content,
            module_path=module_path,
            S_TIER_ENGINEERING_PROTOCOL=S_TIER_ENGINEERING_PROTOCOL,
            RAW_CODE_OUTPUT_RULE=RAW_CODE_OUTPUT_RULE
        )

        full_response = await self._call_llm_agent(prompt, "tester")

        if not full_response:
            self.log("error", f"Tester agent failed to generate test file for '{source_file_path}'.")
            return None

        parts = full_response.split("---requirements.txt---")
        test_code = sanitize_llm_code_output(parts)

        requirements_content = None
        if len(parts) > 1:
            requirements_content = parts.strip()

        self.log("success", f"Successfully generated test file for '{source_file_path}'.")
        return {"test_code": test_code, "requirements": requirements_content}