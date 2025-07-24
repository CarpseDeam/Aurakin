# src/ava/services/implementation_service.py
import asyncio
import json
import re  # Import regular expressions
from typing import Dict, Any, Optional, List, Tuple

from src.ava.core.event_bus import EventBus
from src.ava.prompts import CODER_IMPLEMENT_MARKER_PROMPT  # Use the new Coder prompt
from src.ava.services.base_generation_service import BaseGenerationService


class ImplementationService(BaseGenerationService):
    """Phase 2: Coders fill in the implementation tasks defined in the blueprint."""

    TASK_MARKER_REGEX = re.compile(r"(\s*)# IMPLEMENTATION_TASK: (.*)")

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)

    async def execute(self, blueprint_files: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Executes the implementation phase by finding and replacing task markers.
        """
        self.log("info", "--- Phase 2: Coder agents deploying serially... ---")

        implemented_code = blueprint_files.copy()

        # Create a flat list of all tasks across all files
        all_tasks = []
        for filename, content in blueprint_files.items():
            if filename.endswith('.py'):
                for match in self.TASK_MARKER_REGEX.finditer(content):
                    indentation = match.group(1)
                    description = match.group(2)
                    all_tasks.append((filename, indentation, description, match.group(0)))

        if not all_tasks:
            self.log("warning", "No implementation tasks found in the blueprint.")
            return implemented_code

        # Process tasks serially
        for i, (filename, indentation, description, full_marker_line) in enumerate(all_tasks):
            self.log("info", f"Coder starting task ({i + 1}/{len(all_tasks)}): {description[:80]}...")
            self.event_bus.emit("agent_status_changed", "Coder", f"({i + 1}/{len(all_tasks)}) {description[:50]}...",
                                "fa5s.code")

            if self.project_manager and self.project_manager.active_project_path:
                abs_path_str = str(self.project_manager.active_project_path / filename)
                self.event_bus.emit("agent_activity_started", "Coder", abs_path_str)

            prompt = CODER_IMPLEMENT_MARKER_PROMPT.format(
                file_content=implemented_code[filename],
                task_description=description
            )
            function_body = await self._call_llm_agent(prompt, "coder")

            if not function_body or not function_body.strip():
                self.log("warning",
                         f"Coder failed to provide an implementation for '{description}'. Task marker will be kept.")
                continue

            # --- THE NEW, ROBUST IMPLEMENTATION LOGIC ---
            # Indent the Coder's response to match the marker's indentation level
            indented_body_lines = [f"{indentation}{line}" for line in function_body.splitlines()]
            final_code_block = "\n".join(indented_body_lines)

            # Perform a simple, direct string replacement
            current_file_content = implemented_code[filename]
            implemented_code[filename] = current_file_content.replace(full_marker_line, final_code_block, 1)

            # --- UI UPDATE (Simplified) ---
            # Instead of complex animations, we now just update the whole file at once.
            # This is more robust and avoids the bugs we were seeing.
            self.event_bus.emit("file_content_updated", filename, implemented_code[filename])
            await asyncio.sleep(0.5)  # A small delay to make the UI feel responsive

        return implemented_code