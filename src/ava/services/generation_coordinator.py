# src/ava/services/generation_coordinator.py
import asyncio
import json
from typing import Dict, Any, Optional

from src.ava.core.event_bus import EventBus
from src.ava.prompts import (
    PLANNER_PROMPT, CODER_PROMPT,
    META_ARCHITECT_PROMPT
)
from src.ava.prompts.master_rules import (
    JSON_OUTPUT_RULE, RAW_CODE_OUTPUT_RULE, FILE_PLANNER_PROTOCOL,
    S_TIER_ENGINEERING_PROTOCOL, SENIOR_ARCHITECT_PROTOCOL
)
from src.ava.services.base_generation_service import BaseGenerationService
from src.ava.services.response_validator_service import ResponseValidatorService


class GenerationCoordinator(BaseGenerationService):
    """
    Orchestrates all code generation through a single, robust, hierarchical workflow.
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
        Runs the unified hierarchical workflow for both creation and modification.
        """
        self.event_bus.emit("build_workflow_started")

        # --- PHASE 0: META-ARCHITECT - HIGH-LEVEL PLANNING ---
        self.log("info", "--- Starting Unified Hierarchical Workflow ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Devising high-level strategy...", "fa5s.brain")

        # Provide existing files as context if they exist, otherwise provide an empty dict.
        context_files_json = json.dumps(existing_files, indent=2) if existing_files else "{}"

        meta_prompt = META_ARCHITECT_PROMPT.format(
            user_request=user_request,
            existing_files_json=context_files_json,
            SENIOR_ARCHITECT_PROTOCOL=SENIOR_ARCHITECT_PROTOCOL,
            JSON_OUTPUT_RULE=JSON_OUTPUT_RULE
        )

        meta_response = await self._call_llm_agent(meta_prompt, "architect")

        if not meta_response:
            self.log("error", "Meta-Architect failed to produce a high-level plan. Aborting.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        parsed_strategy = self.validator.extract_and_parse_json(meta_response)
        if not parsed_strategy:
            self.log("error", f"Meta-Architect produced invalid JSON. Response: {meta_response[:300]}")
            self.event_bus.emit("ai_workflow_finished")
            return None

        high_level_plan = parsed_strategy.get("high_level_plan", "No plan provided.")
        pydantic_models = parsed_strategy.get("pydantic_models", "")
        self.log("success", f"Meta-Architect devised a strategy: {high_level_plan}")

        # --- PHASE 1: FILE PLANNER - DETAILED FILE CONTRACT ---
        self.event_bus.emit("agent_status_changed", "Architect", "Designing file-by-file interface contract...",
                            "fa5s.drafting-compass")

        planner_prompt = PLANNER_PROMPT.format(
            user_request=user_request,
            high_level_plan=high_level_plan,
            pydantic_models=pydantic_models,
            FILE_PLANNER_PROTOCOL=FILE_PLANNER_PROTOCOL,
            JSON_OUTPUT_RULE=JSON_OUTPUT_RULE
        )

        planner_response = await self._call_llm_agent(planner_prompt, "architect")

        if not planner_response:
            self.log("error", "File Planner agent returned an empty response. Aborting generation.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        parsed_json = self.validator.extract_and_parse_json(planner_response)
        interface_contract = parsed_json.get("interface_contract") if parsed_json else None

        if not isinstance(interface_contract, list) or not interface_contract:
            self.log("error",
                     f"File Planner failed to return a valid interface contract. Response: {planner_response[:300]}")
            self.event_bus.emit("ai_workflow_finished")
            return None

        if self.project_manager and self.project_manager.active_project_path:
            self.event_bus.emit("agent_activity_started", "Architect", str(self.project_manager.active_project_path))
            await asyncio.sleep(1.5)

        files_to_generate = {item.get('file'): "" for item in interface_contract if item.get('file')}
        self.log("success", f"File Planner designed {len(files_to_generate)} files.")

        # For new projects, this creates the initial placeholders. For modifications, it adds new ones.
        self.event_bus.emit("project_scaffold_generated", files_to_generate)
        await asyncio.sleep(0.5)

        # --- PHASE 2: CODER - FILE-BY-FILE IMPLEMENTATION ---
        # Start with the existing files and overwrite them with newly generated content.
        final_code = existing_files.copy() if existing_files else {}

        for i, contract_item in enumerate(interface_contract):
            target_file = contract_item.get("file")
            purpose = contract_item.get("purpose", "No purpose defined.")
            public_members = contract_item.get("public_members", [])
            if not target_file:
                continue

            self.log("info", f"Coder starting file ({i + 1}/{len(files_to_generate)}): {target_file}")
            self.event_bus.emit("agent_status_changed", "Coder",
                                f"Writing {target_file} ({i + 1}/{len(files_to_generate)})...", "fa5s.code")
            self.event_bus.emit("file_content_updated", target_file, "")  # Clear the tab before streaming

            # ... (Rest of Coder logic is the same)
            file_content = ""
            made_api_call = True  # Assume we'll call the API

            if "pydantic_models" in parsed_strategy and pydantic_models and target_file.endswith(
                    (".py")) and "models" in target_file:
                file_content = pydantic_models
                made_api_call = False
            elif target_file == 'requirements.txt':
                # For modifications, append to existing requirements if possible.
                reqs = set((existing_files.get(target_file, "")).splitlines())
                reqs.add("pytest")
                if "pydantic" in pydantic_models.lower():
                    reqs.add("pydantic")
                file_content = "\n".join(sorted(list(filter(None, reqs))))
                made_api_call = False
            elif target_file == '.gitignore':
                file_content = "# Kintsugi AvA Default Ignore\n.venv/\nvenv/\n__pycache__/\n*.py[co]\nrag_db/\n.env\n*.log\n"
                made_api_call = False
            elif target_file.endswith('__init__.py'):
                file_content = ""  # Empty __init__.py
                made_api_call = False

            if not made_api_call:
                self.event_bus.emit("stream_text_at_cursor", target_file, file_content)
            else:
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
                    public_members=public_members,
                    S_TIER_ENGINEERING_PROTOCOL=S_TIER_ENGINEERING_PROTOCOL,
                    RAW_CODE_OUTPUT_RULE=RAW_CODE_OUTPUT_RULE
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

            final_code[target_file] = file_content
            self.event_bus.emit("finalize_editor_content", target_file)
            if made_api_call:
                await asyncio.sleep(1.1)

        self.log("success", "✅ Unified Workflow Finished Successfully.")
        self.event_bus.emit("ai_workflow_finished")
        return final_code