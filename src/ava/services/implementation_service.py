# src/ava/services/implementation_service.py
import asyncio
import json
import re
from typing import Dict, Any, Optional, List, Tuple

from src.ava.core.event_bus import EventBus
from src.ava.prompts import CODER_IMPLEMENT_MARKER_PROMPT
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
                # We need to find the line number for each match
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    match = self.TASK_MARKER_REGEX.match(line)
                    if match:
                        line_number = i + 1
                        indentation = match.group(1)
                        description = match.group(2)
                        all_tasks.append((filename, indentation, description, line.strip(), line_number))

        if not all_tasks:
            self.log("warning", "No implementation tasks found in the blueprint.")
            return implemented_code

        # Process tasks serially
        for i, (filename, indentation, description, full_marker_line, line_number) in enumerate(all_tasks):
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

            # --- BRINGING BACK THE ANIMATION! ---
            # 1. Highlight the task marker line that will be replaced.
            self.event_bus.emit("highlight_lines_for_edit", filename, line_number, line_number)
            await asyncio.sleep(0.4)

            # 2. Delete the highlighted line.
            self.event_bus.emit("delete_highlighted_lines", filename)
            await asyncio.sleep(0.2)

            # 3. Stream in the new, correctly indented code.
            indented_body_lines = [f"{indentation}{line}" for line in function_body.splitlines()]
            text_to_insert = "\n".join(indented_body_lines)

            for char in text_to_insert:
                self.event_bus.emit("stream_text_at_cursor", filename, char)
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.2)

            # --- UPDATE INTERNAL STATE ROBUSTLY ---
            # Instead of a simple replace, we rebuild the file from lines to be 100% sure.
            # This avoids any issues if the same marker appears twice.
            lines = implemented_code[filename].splitlines()
            # Find the line with the marker and replace it
            for line_idx, line_content in enumerate(lines):
                if line_content.strip() == full_marker_line:
                    lines[line_idx:line_idx + 1] = indented_body_lines
                    break

            implemented_code[filename] = "\n".join(lines)

            # Finalize the editor content
            self.event_bus.emit("finalize_editor_content", filename)

        return implemented_code