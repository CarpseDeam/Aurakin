# src/ava/services/generation_coordinator.py
import asyncio
import json
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
# The import line should now work perfectly!
from src.ava.prompts import (
    PLANNER_PROMPT, CODER_PROMPT,
    MODIFICATION_PLANNER_PROMPT, MODIFICATION_CODER_PROMPT
)
from src.ava.services.base_generation_service import BaseGenerationService
from src.ava.services.response_validator_service import ResponseValidatorService


class GenerationCoordinator(BaseGenerationService):
    """
    Orchestrates code generation, handling both creation from scratch
    and surgical modification of existing code.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.validator = ResponseValidatorService()

    async def coordinate_generation(
            self,
            existing_files: Optional[Dict[str, str]],
            user_request: str
    ) -> Optional[Dict[str, str]]:
        """
        Routes to the correct generation workflow based on whether
        it's a new project or a modification.
        """
        self.event_bus.emit("build_workflow_started")

        if existing_files:
            return await self._run_modification_workflow(existing_files, user_request)
        else:
            return await self._run_creation_workflow(user_request)

    async def _run_creation_workflow(self, user_request: str) -> Optional[Dict[str, str]]:
        """Handles the generation of a new project from scratch."""
        self.log("info", "--- Starting Creation Workflow ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Designing interface contract...",
                            "fa5s.drafting-compass")

        planner_prompt = PLANNER_PROMPT.format(user_request=user_request)
        planner_response = await self._call_llm_agent(planner_prompt, "architect")

        if not planner_response:
            self.log("error", "Planner agent returned an empty response. Aborting generation.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        parsed_json = self.validator.extract_and_parse_json(planner_response)
        interface_contract = parsed_json.get("interface_contract") if parsed_json else None

        if not isinstance(interface_contract, list) or not interface_contract:
            self.log("error",
                     f"Planner agent failed to return a valid interface contract. Response: {planner_response[:300]}")
            self.event_bus.emit("ai_workflow_finished")
            return None

        files_to_create = [item.get('file') for item in interface_contract if item.get('file')]
        self.log("success", f"Architect planned {len(files_to_create)} files with interface contracts.")
        self.event_bus.emit("project_scaffold_generated", {path: "" for path in files_to_create})
        await asyncio.sleep(0.5)

        generated_files: Dict[str, str] = {}
        for i, contract_item in enumerate(interface_contract):
            target_file = contract_item.get("file")
            purpose = contract_item.get("purpose", "No purpose defined.")
            public_members = contract_item.get("public_members", [])
            if not target_file:
                continue

            self.log("info", f"Coder starting file ({i + 1}/{len(files_to_create)}): {target_file}")
            self.event_bus.emit("agent_status_changed", "Coder",
                                f"Writing {target_file} ({i + 1}/{len(files_to_create)})...", "fa5s.code")
            self.event_bus.emit("file_content_updated", target_file, "")

            context_blocks = []
            for other_item in interface_contract:
                if other_item.get('file') == target_file or not other_item.get('public_members'):
                    continue
                members_str = "\n".join([f"    # {sig}" for sig in other_item['public_members']])
                context_blocks.append(f"  # From {other_item.get('file')}:\n{members_str}")
            interface_context = "class ProjectInterfaces:\n" + "\n\n".join(
                context_blocks) if context_blocks else "# No other interfaces defined."

            file_content = ""
            made_api_call = False
            if target_file == '.gitignore':
                file_content = "# Kintsugi AvA Default Ignore\n.venv/\nvenv/\n__pycache__/\n*.py[co]\nrag_db/\n.env\n*.log\n"
                self.event_bus.emit("stream_text_at_cursor", target_file, file_content)
            elif target_file.endswith('__init__.py'):
                file_content = ""
            else:
                made_api_call = True
                if self.project_manager and self.project_manager.active_project_path:
                    abs_path_str = str(self.project_manager.active_project_path / target_file)
                    self.event_bus.emit("agent_activity_started", "Coder", abs_path_str)
                await asyncio.sleep(0.1)

                coder_prompt = CODER_PROMPT.format(
                    user_request=user_request,
                    target_file=target_file,
                    purpose=purpose,
                    interface_context=interface_context,
                    public_members=public_members
                )
                full_streamed_content = ""
                async for chunk in self._stream_llm_agent_chunks(coder_prompt, "coder"):
                    if chunk.startswith("LLM_API_ERROR:"):
                        self.log("error", f"Coder agent failed for {target_file}: {chunk}")
                        full_streamed_content = None
                        break
                    self.event_bus.emit("stream_text_at_cursor", target_file, chunk)
                    full_streamed_content += chunk
                if full_streamed_content is None:
                    self.event_bus.emit("ai_workflow_finished")
                    return None
                file_content = full_streamed_content

            generated_files[target_file] = file_content
            self.event_bus.emit("finalize_editor_content", target_file)
            if made_api_call:
                await asyncio.sleep(1.1)

        self.log("success", "✅ Creation Workflow Finished Successfully.")
        self.event_bus.emit("ai_workflow_finished")
        return generated_files

    async def _run_modification_workflow(self, existing_files: Dict[str, str], user_request: str) -> Optional[
        Dict[str, str]]:
        self.log("info", "--- Starting Modification Workflow ---")

        # Phase 1: Create the Surgical Plan
        self.event_bus.emit("agent_status_changed", "Surgeon", "Planning modifications...", "fa5s.tasks")
        planner_prompt = MODIFICATION_PLANNER_PROMPT.format(
            user_request=user_request,
            existing_files_json=json.dumps(list(existing_files.keys()), indent=2)
        )
        plan_response = await self._call_llm_agent(planner_prompt, "architect")
        surgical_plan = self.validator.extract_and_parse_json(plan_response)

        if not surgical_plan:
            self.log("error", "Surgical Planner failed to produce a valid plan.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        files_to_modify = surgical_plan.get("files_to_modify", [])
        files_to_create = surgical_plan.get("files_to_create", [])

        modified_code = existing_files.copy()

        # Phase 2: Create new files (if any)
        for item in files_to_create:
            # This part is simplified for now. We can use the creation workflow later.
            target_file = item.get('file')
            self.log("info", f"Surgeon needs to create new file: {target_file}")
            modified_code[target_file] = f"# New file for: {item.get('purpose')}\n"
            self.event_bus.emit("file_content_updated", target_file, modified_code[target_file])

        # Phase 3: Modify existing files
        for item in files_to_modify:
            target_file = item.get("file")
            reason = item.get("reason_for_change")
            if not target_file or target_file not in existing_files:
                continue

            self.log("info", f"Surgeon is operating on: {target_file}")
            self.event_bus.emit("agent_status_changed", "Surgeon", f"Modifying {target_file}...", "fa5s.cut")

            coder_prompt = MODIFICATION_CODER_PROMPT.format(
                reason_for_change=reason,
                target_file=target_file,
                original_code=existing_files[target_file]
            )

            edits_response = await self._call_llm_agent(coder_prompt, "coder")
            edits_json = self.validator.extract_and_parse_json(edits_response)

            if edits_json and (edits := edits_json.get("edits")):
                modified_code[target_file] = await self._apply_animated_edits(
                    target_file,
                    modified_code[target_file],
                    edits
                )

        self.log("success", "✅ Modification Workflow Finished Successfully.")
        self.event_bus.emit("ai_workflow_finished")
        return modified_code

    async def _apply_animated_edits(self, filename: str, original_content: str, edits: List[Dict]) -> str:
        """Applies a list of edits to a file's content with UI animations."""
        lines = original_content.splitlines()
        # Sort edits from bottom to top to avoid line number conflicts
        edits.sort(key=lambda x: x.get('start_line', 0), reverse=True)

        for edit in edits:
            start = edit.get("start_line")
            end = edit.get("end_line")
            replacement = edit.get("replacement_code")

            if not all([start, end, replacement is not None]):
                continue

            # UI Animation
            self.event_bus.emit("highlight_lines_for_edit", filename, start, end)
            await asyncio.sleep(1.0)  # Pause for user to see

            # Apply the change to the lines list
            # Line numbers are 1-based, list indices are 0-based
            lines[start - 1: end] = replacement.splitlines()

            # Update the UI with the *current* state of the file
            self.event_bus.emit("file_content_updated", filename, "\n".join(lines))
            await asyncio.sleep(0.5)

        return "\n".join(lines)