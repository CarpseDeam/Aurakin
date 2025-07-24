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

    def _extract_context_for_task(self, lines: List[str], task_line_index: int) -> Dict[str, str]:
        """
        Finds the function/class signature and docstring that precedes a task marker.
        """
        task_line = lines[task_line_index]
        task_indentation = len(task_line) - len(task_line.lstrip(' '))

        signature = "Could not determine signature."
        docstring = "Could not extract docstring."
        signature_line_index = -1

        # Scan backwards to find the function/class definition
        for i in range(task_line_index - 1, -1, -1):
            line = lines[i]
            stripped_line = line.strip()
            if stripped_line.startswith(('def ', 'class ')):
                line_indentation = len(line) - len(line.lstrip(' '))
                if line_indentation < task_indentation:
                    signature = stripped_line
                    signature_line_index = i
                    break

        # Scan forwards from the definition to find the docstring
        if signature_line_index != -1:
            docstring_lines = []
            in_docstring = False
            for i in range(signature_line_index + 1, task_line_index):
                line = lines[i].strip()
                if line.startswith(('"""', "'''")):
                    if in_docstring:
                        in_docstring = False
                        docstring_lines.append(line)
                        break
                    else:
                        in_docstring = True
                        docstring_lines.append(line)
                elif in_docstring:
                    docstring_lines.append(line)

            if docstring_lines:
                docstring = "\n".join(docstring_lines)

        return {"signature": signature, "docstring": docstring}

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
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    match = self.TASK_MARKER_REGEX.match(line)
                    if match:
                        line_number = i + 1
                        indentation = match.group(1)
                        description = match.group(2)
                        context = self._extract_context_for_task(lines, i)
                        all_tasks.append((filename, indentation, description, line.strip(), line_number, context))

        if not all_tasks:
            self.log("warning", "No implementation tasks found in the blueprint.")
            return implemented_code

        # Process tasks serially
        for i, (filename, indentation, description, full_marker_line, line_number, context) in enumerate(all_tasks):
            self.log("info", f"Coder starting task ({i + 1}/{len(all_tasks)}): {description[:80]}...")
            self.event_bus.emit("agent_status_changed", "Coder", f"({i + 1}/{len(all_tasks)}) {description[:50]}...",
                                "fa5s.code")

            if self.project_manager and self.project_manager.active_project_path:
                abs_path_str = str(self.project_manager.active_project_path / filename)
                self.event_bus.emit("agent_activity_started", "Coder", abs_path_str)

            prompt = CODER_IMPLEMENT_MARKER_PROMPT.format(
                file_content=implemented_code[filename],
                task_description=description,
                function_signature=context['signature'],
                function_docstring=context['docstring']
            )
            function_body = await self._call_llm_agent(prompt, "coder")

            if not function_body or not function_body.strip():
                self.log("warning",
                         f"Coder failed to provide an implementation for '{description}'. Task marker will be kept.")
                continue

            indented_body_lines = [f"{indentation}{line}" for line in function_body.splitlines()]

            lines = implemented_code[filename].splitlines()
            for line_idx, line_content in enumerate(lines):
                if line_content.strip() == full_marker_line:
                    lines[line_idx:line_idx + 1] = indented_body_lines
                    break

            implemented_code[filename] = "\n".join(lines)
            self.event_bus.emit("file_content_updated", filename, implemented_code[filename])
            await asyncio.sleep(0.1)  # Small delay for UI to catch up

        return implemented_code