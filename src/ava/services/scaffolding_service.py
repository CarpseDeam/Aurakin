# src/ava/services/scaffolding_service.py
import asyncio
import ast
import re
from typing import Dict, Any, Optional

from src.ava.core.event_bus import EventBus
from src.ava.prompts import ARCHITECT_BLUEPRINT_PROMPT
from src.ava.services.base_generation_service import BaseGenerationService
# --- THIS IS THE FIX ---
# We change the import to be a direct, relative import.
# This tells Python "look in the current folder," which avoids the circular dependency.
from .response_validator_service import ResponseValidatorService


# --- END FIX ---


class ScaffoldingService(BaseGenerationService):
    """Phase 1: Architect builds the project blueprint and this service sanitizes it."""

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.validator = ResponseValidatorService()

    def _sanitize_scaffold_code(self, code: str) -> str:
        """
        The definitive, "brute-force" sanitizer. It ensures every function/class
        definition has a body, and is robust against end-of-file errors.
        """
        lines = code.split('\n')
        sanitized_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            sanitized_lines.append(line)
            stripped_line = line.strip()

            if stripped_line.startswith(('def ', 'class ', 'async def ')) and stripped_line.endswith(':'):
                current_indent = len(line) - len(line.lstrip(' '))

                # Look ahead to find the next line with actual code
                next_code_line_found = False
                for j in range(i + 1, len(lines)):
                    next_line = lines[j]
                    if next_line.strip():  # If the line is not just whitespace
                        next_line_indent = len(next_line) - len(next_line.lstrip(' '))
                        # If the next code line is not indented further, the body is missing
                        if next_line_indent <= current_indent:
                            pass_statement = ' ' * (current_indent + 4) + 'pass'
                            sanitized_lines.append(pass_statement)
                            self.log("warning", f"Sanitizer: Added missing 'pass' to definition on line {i + 1}.")
                        next_code_line_found = True
                        break

                # If we reached the end of the file without finding any more code, the body was missing
                if not next_code_line_found:
                    pass_statement = ' ' * (current_indent + 4) + 'pass'
                    sanitized_lines.append(pass_statement)
                    self.log("warning", f"Sanitizer: Added missing 'pass' to definition at end of file.")

            i += 1

        return "\n".join(sanitized_lines)

    async def execute(self, user_request: str) -> Optional[Dict[str, str]]:
        """
        Executes the scaffolding phase, including the new sanitization step.
        """
        self.log("info", "--- Phase 1: Architect is building the project skeleton... ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Designing project skeleton...",
                            "fa5s.drafting-compass")

        prompt = ARCHITECT_BLUEPRINT_PROMPT.format(user_request=user_request)
        raw_response = await self._call_llm_agent(prompt, "architect")

        if not raw_response:
            self.log("error", "Architect returned an empty response.")
            return None

        parsed_json = self.validator.extract_and_parse_json(raw_response)
        if not parsed_json:
            self.log("error",
                     f"Validator could not extract valid JSON from Architect's response. Response: {raw_response[:500]}")
            return None

        scaffold_files = self.validator.validate_and_flatten_scaffold(parsed_json)
        if not scaffold_files:
            self.log("error", "Validator could not process the parsed JSON into a valid scaffold structure.")
            return None

        # --- THE ADAPTER: SANITIZE AND VALIDATE ---
        sanitized_scaffold = {}
        for filename, content in scaffold_files.items():
            if filename.endswith('.py'):
                # In the 'Blueprint' model, we no longer need a sanitizer. The AI is instructed
                # to produce syntactically valid code with comment markers.
                # sanitized_content = self._sanitize_scaffold_code(content)

                try:
                    # We just validate it.
                    ast.parse(content)
                    sanitized_scaffold[filename] = content
                except SyntaxError as e:
                    self.log("error", f"CRITICAL: Architect produced code in '{filename}' that is not valid Python.")
                    self.log("error", f"Syntax Error: {e}")
                    self.log("error", "Aborting generation.")
                    return None
            else:
                # For non-python files, just add them directly.
                sanitized_scaffold[filename] = content

        self.log("success", "Architect's blueprint has been validated.")
        # --- END OF ADAPTER ---

        self.event_bus.emit("project_scaffold_generated", sanitized_scaffold)
        await asyncio.sleep(0.5)
        return sanitized_scaffold