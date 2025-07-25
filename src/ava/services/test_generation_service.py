# src/ava/services/test_generation_service.py
from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Any

from src.ava.prompts import TESTER_PROMPT
from src.ava.services.base_generation_service import BaseGenerationService

if TYPE_CHECKING:
    from src.ava.core.event_bus import EventBus


class TestGenerationService(BaseGenerationService):
    """
    A specialized service to handle the generation of unit tests for a single function.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.log("info", "TestGenerationService Initialized.")

    async def generate_test_for_function(self, function_name: str, function_code: str, source_file_path: str) -> Optional[str]:
        """
        Generates a pytest file content for a given function.

        Args:
            function_name: The name of the function to test.
            function_code: The full source code of the function.
            source_file_path: The relative path to the file containing the function.

        Returns:
            The complete content of the generated pytest file as a string, or None on failure.
        """
        self.log("info", f"Generating unit test for function '{function_name}' from '{source_file_path}'.")
        self.event_bus.emit("agent_status_changed", "Tester", f"Generating test for {function_name}", "fa5s.vial")

        # Construct the module path for the import statement in the test file.
        # e.g., 'src/calculator/operations.py' -> 'src.calculator.operations'
        module_path = source_file_path.replace('/', '.').replace('\\\\', '.').removesuffix('.py')

        prompt = TESTER_PROMPT.format(
            function_name=function_name,
            function_code=function_code,
            module_path=module_path
        )

        test_file_content = await self._call_llm_agent(prompt, "tester")

        if not test_file_content:
            self.log("error", f"Tester agent failed to generate content for function '{function_name}'.")
            return None

        self.log("success", f"Successfully generated test content for '{function_name}'.")
        return test_file_content