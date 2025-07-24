# src/ava/services/generation_coordinator.py
import asyncio
import json
from typing import Dict, Any, Optional

from src.ava.core.event_bus import EventBus
from src.ava.prompts import PLANNER_PROMPT, CODER_PROMPT
from src.ava.services.base_generation_service import BaseGenerationService

from src.ava.services.response_validator_service import ResponseValidatorService


class GenerationCoordinator(BaseGenerationService):
    """
    Orchestrates the new iterative, file-by-file generation workflow.
    This is more robust than the previous single-shot blueprint approach.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.validator = ResponseValidatorService()

    async def coordinate_generation(
            self,
            existing_files: Optional[Dict[str, str]],
            user_request: str
    ) -> Optional[Dict[str, str]]:
        """Executes the new generation pipeline."""
        self.event_bus.emit("build_workflow_started")

        # --- PHASE 1: PLANNING ---
        self.log("info", "--- Phase 1: Architect is planning the file structure... ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Planning file structure...", "fa5s.drafting-compass")

        planner_prompt = PLANNER_PROMPT.format(user_request=user_request)
        planner_response = await self._call_llm_agent(planner_prompt, "architect")

        if not planner_response:
            self.log("error", "Planner agent returned an empty response. Aborting generation.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        parsed_json = self.validator.extract_and_parse_json(planner_response)
        files_to_create = parsed_json.get("files_to_create") if parsed_json else None

        if not isinstance(files_to_create, list) or not files_to_create:
            self.log("error",
                     f"Planner agent failed to return a valid list of files. Response: {planner_response[:300]}")
            self.event_bus.emit("ai_workflow_finished")
            return None

        self.log("success", f"Architect planned {len(files_to_create)} files.")
        self.event_bus.emit("project_scaffold_generated", {path: "" for path in files_to_create})
        await asyncio.sleep(0.5)

        # --- PHASE 2: ITERATIVE, STREAMING GENERATION ---
        self.log("info", "--- Phase 2: Coder is generating files one by one... ---")
        generated_files: Dict[str, str] = {}
        file_list_str = "\n".join(f"- {f}" for f in files_to_create)

        for i, target_file in enumerate(files_to_create):
            self.log("info", f"Coder starting file ({i + 1}/{len(files_to_create)}): {target_file}")
            self.event_bus.emit("agent_status_changed", "Coder",
                                f"Writing {target_file} ({i + 1}/{len(files_to_create)})...", "fa5s.code")
            self.event_bus.emit("file_content_updated", target_file, "")  # Create/Focus tab

            file_content = ""
            made_api_call = False

            # --- THIS IS THE FIX ---
            # Handle boilerplate files locally instead of calling the AI.
            if target_file == '.gitignore':
                self.log("info", f"Generating '{target_file}' locally.")
                file_content = "# Kintsugi AvA Default Ignore\n.venv/\nvenv/\n__pycache__/\n*.py[co]\nrag_db/\n.env\n*.log\n"
                self.event_bus.emit("stream_text_at_cursor", target_file, file_content)

            elif target_file.endswith('__init__.py'):
                self.log("info", f"Generating '{target_file}' locally.")
                # Empty content is fine, the file just needs to exist.
                file_content = ""

            elif target_file == 'requirements.txt':
                self.log("info", f"Generating '{target_file}' locally.")
                # Empty content for now, as we don't know dependencies yet.
                file_content = ""

            else:
                # For all other files, call the AI as normal.
                made_api_call = True
                if self.project_manager and self.project_manager.active_project_path:
                    abs_path_str = str(self.project_manager.active_project_path / target_file)
                    self.event_bus.emit("agent_activity_started", "Coder", abs_path_str)
                await asyncio.sleep(0.1)

                coder_prompt = CODER_PROMPT.format(
                    user_request=user_request,
                    file_list=file_list_str,
                    target_file=target_file
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
                    self.log("error", f"Aborting generation due to API error on {target_file}.")
                    self.event_bus.emit("ai_workflow_finished")
                    return None

                file_content = full_streamed_content
            # --- END OF FIX ---

            if not file_content.strip() and not target_file.endswith("__init__.py"):
                placeholder = f'# NOTE: The AI generated an empty file here. You may need to add content.'
                # If we didn't stream, we need to send the placeholder now.
                if not made_api_call:
                    self.event_bus.emit("stream_text_at_cursor", target_file, placeholder)
                file_content = placeholder

            generated_files[target_file] = file_content
            self.event_bus.emit("finalize_editor_content", target_file)

            if made_api_call:
                self.log("info", f"Waiting for 1.1s to respect API rate limits...")
                await asyncio.sleep(1.1)

        self.log("success", "✅ Iterative Generation Finished Successfully.")
        self.event_bus.emit("ai_workflow_finished")
        return generated_files