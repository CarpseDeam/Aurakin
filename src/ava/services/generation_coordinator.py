# src/ava/services/generation_coordinator.py
import asyncio
import difflib
import json
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
from src.ava.prompts import (
    PLANNER_PROMPT, CODER_PROMPT,
    MODIFICATION_REWRITER_PROMPT
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

    def _sanitize_code_output(self, raw_code: str) -> str:
        """Removes markdown fences and leading/trailing whitespace from LLM-generated code."""
        if raw_code.startswith("```python"):
            raw_code = raw_code[len("```python"):].strip()
        elif raw_code.startswith("```"):
            raw_code = raw_code[len("```"):].strip()
        if raw_code.endswith("```"):
            raw_code = raw_code[:-len("```")].strip()
        return raw_code

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

            file_content = ""
            made_api_call = False
            # --- NEW: Foolproof handling for requirements.txt and other boilerplate ---
            if target_file == 'requirements.txt':
                file_content = "pytest\n"
                self.event_bus.emit("stream_text_at_cursor", target_file, file_content)
            elif target_file == '.gitignore':
                file_content = "# Kintsugi AvA Default Ignore\n.venv/\nvenv/\n__pycache__/\n*.py[co]\nrag_db/\n.env\n*.log\n"
                self.event_bus.emit("stream_text_at_cursor", target_file, file_content)
            elif target_file.endswith('__init__.py'):
                file_content = "" # Blank file, no stream needed
            else:
                made_api_call = True
                if self.project_manager and self.project_manager.active_project_path:
                    abs_path_str = str(self.project_manager.active_project_path / target_file)
                    self.event_bus.emit("agent_activity_started", "Coder", abs_path_str)
                await asyncio.sleep(0.1)

                context_blocks = []
                for other_item in interface_contract:
                    if other_item.get('file') == target_file or not other_item.get('public_members'):
                        continue
                    members_str = "\n".join([f"    # {sig}" for sig in other_item['public_members']])
                    context_blocks.append(f"  # From {other_item.get('file')}:\n{members_str}")
                interface_context = "class ProjectInterfaces:\n" + "\n\n".join(
                    context_blocks) if context_blocks else "# No other interfaces defined."

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
                file_content = self._sanitize_code_output(full_streamed_content)

            generated_files[target_file] = file_content
            self.event_bus.emit("finalize_editor_content", target_file)
            if made_api_call:
                await asyncio.sleep(1.1)

        self.log("success", "✅ Creation Workflow Finished Successfully.")
        self.event_bus.emit("ai_workflow_finished")
        return generated_files

    async def _run_modification_workflow(self, existing_files: Dict[str, str], user_request: str) -> Optional[
        Dict[str, str]]:
        self.log("info", "--- Starting Rewrite-and-Diff Modification Workflow ---")

        self.event_bus.emit("agent_status_changed", "Rewriter", "Analyzing and rewriting files...", "fa5s.edit")

        rewriter_prompt = MODIFICATION_REWRITER_PROMPT.format(
            user_request=user_request,
            existing_files_json=json.dumps(existing_files, indent=2)
        )

        rewriter_response = await self._call_llm_agent(rewriter_prompt, "architect")

        if not rewriter_response or not rewriter_response.strip():
            self.log("error", "Rewriter agent returned an empty response. Aborting modification.")
            self.event_bus.emit("ai_workflow_finished")
            return existing_files

        rewritten_files = self.validator.extract_and_parse_json(rewriter_response)

        if not isinstance(rewritten_files, dict):
            self.log("error",
                     f"Rewriter agent failed to return a valid JSON dictionary of files. Response: {rewriter_response[:300]}")
            self.event_bus.emit("ai_workflow_finished")
            return existing_files

        if not rewritten_files:
            self.log("warning", "Rewriter agent returned no files to modify. Assuming no changes were needed.")
            self.event_bus.emit("ai_workflow_finished")
            return existing_files

        self.log("success", f"Rewriter agent has provided new versions for {len(rewritten_files)} file(s).")

        final_code = existing_files.copy()

        for filename, new_content in rewritten_files.items():
            self.log("info", f"Applying character-stream animation for '{filename}'")

            if self.project_manager and self.project_manager.active_project_path:
                abs_path_str = str(self.project_manager.active_project_path / filename)
                self.event_bus.emit("agent_activity_started", "Rewriter", abs_path_str)

            self.event_bus.emit("file_content_updated", filename, "")
            await asyncio.sleep(0.1)

            for char in new_content:
                self.event_bus.emit("stream_text_at_cursor", filename, char)
                await asyncio.sleep(0.001)

            self.event_bus.emit("finalize_editor_content", filename)
            final_code[filename] = new_content
            await asyncio.sleep(0.5)

        self.log("success", "✅ Modification Workflow Finished Successfully.")
        self.event_bus.emit("ai_workflow_finished")
        return final_code