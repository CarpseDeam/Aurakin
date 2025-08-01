import asyncio
import json
import textwrap
from typing import Dict, Any, Optional

from src.ava.core.event_bus import EventBus
from src.ava.prompts import (META_ARCHITECT_PROMPT, PLANNER_PROMPT, CODER_PROMPT,
                             REVIEWER_PROMPT, CORRECTOR_PROMPT)
from src.ava.prompts.master_rules import SENIOR_ARCHITECT_PROTOCOL, JSON_OUTPUT_RULE, FILE_PLANNER_PROTOCOL, \
    S_TIER_ENGINEERING_PROTOCOL, RAW_CODE_OUTPUT_RULE
from src.ava.services.base_generation_service import BaseGenerationService

from src.ava.services.response_validator_service import ResponseValidatorService
from src.ava.utils import sanitize_llm_code_output
from src.ava.utils.code_summarizer import CodeSummarizer


class GenerationCoordinator(BaseGenerationService):
    """
    Orchestrates all code generation through a single, robust, hierarchical workflow.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)
        self.validator = ResponseValidatorService()
        self.import_fixer = self.service_manager.get_import_fixer_service()
        self.indexer = self.service_manager.get_project_indexer_service()

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

        if self.project_manager and self.project_manager.active_project_path:
            self.event_bus.emit("agent_activity_started", "Architect", str(self.project_manager.active_project_path))
            await asyncio.sleep(0.1)

        project_summary = ""
        if existing_files:
            summary_parts = []
            for path, content in existing_files.items():
                if path.endswith('.py'):
                    summarizer = CodeSummarizer(content)
                    summary = summarizer.summarize()
                    summary_parts.append(f"# FILE: {path}\n{summary}\n")
            project_summary = "\n".join(summary_parts)

        meta_prompt = META_ARCHITECT_PROMPT.format(
            user_request=user_request,
            project_summary=project_summary or "# This is a new project.",
            SENIOR_ARCHITECT_PROTOCOL=SENIOR_ARCHITECT_PROTOCOL,
            JSON_OUTPUT_RULE=JSON_OUTPUT_RULE
        )

        meta_response = await self._call_llm_agent(meta_prompt, "architect", max_tokens=16384)

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

        # --- PHASE 1: FILE PLANNER - DETAILED "IRONCLAD" CONTRACT ---
        self.event_bus.emit("agent_status_changed", "Architect", "Designing Ironclad Contract...",
                            "fa5s.drafting-compass")

        planner_prompt = PLANNER_PROMPT.format(
            user_request=user_request,
            high_level_plan=high_level_plan,
            pydantic_models=pydantic_models,
            FILE_PLANNER_PROTOCOL=FILE_PLANNER_PROTOCOL,
            JSON_OUTPUT_RULE=JSON_OUTPUT_RULE
        )

        planner_response = await self._call_llm_agent(planner_prompt, "architect", max_tokens=16384)
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

        files_to_generate = {item.get('file'): "" for item in interface_contract if item.get('file')}
        self.log("success", f"File Planner designed {len(files_to_generate)} files.")

        self.event_bus.emit("project_scaffold_generated", files_to_generate)
        await asyncio.sleep(0.5)

        # --- PHASE 2: CODER & REVIEWER - FILE-BY-FILE IMPLEMENTATION & REFINEMENT ---
        final_code = existing_files.copy() if existing_files else {}
        project_index = {name: mod for file, content in final_code.items() for name, mod in
                         self.indexer.get_symbols_from_content(content,
                                                               file.replace('/', '.').removesuffix('.py')).items()}

        for i, contract_item in enumerate(interface_contract):
            target_file = contract_item.get("file")
            if not target_file:
                continue

            self.log("info", f"Generation starting for file ({i + 1}/{len(interface_contract)}): {target_file}")

            purpose = contract_item.get("purpose", "# No purpose defined.")
            imports = "\n".join(contract_item.get("imports", []))

            public_members_spec_list = []
            for member in contract_item.get("public_members", []):
                notes = "\n".join([f"      - {note}" for note in member.get("implementation_notes", [])])
                spec = (f"  - **Type**: {member.get('type', 'N/A')}\n"
                        f"  - **Name**: {member.get('name', 'N/A')}\n"
                        f"  - **Signature**: `def {member.get('name', '')}{member.get('signature', '')}`\n"
                        f"  - **Docstring**: \n\"\"\"\n{member.get('docstring', '')}\n\"\"\"\n"
                        f"  - **Implementation Notes**:\n{notes}")
                public_members_spec_list.append(spec)
            public_members_specs = "\n\n".join(public_members_spec_list)

            context_blocks = []
            for other_item in interface_contract:
                if other_item.get('file') == target_file or not other_item.get('public_members'): continue
                for member in other_item['public_members']:
                    context_blocks.append(
                        f"  # From {other_item.get('file')}: def {member.get('name', '')}{member.get('signature', '')}")
            interface_context = "class ProjectInterfaces:\n" + "\n".join(
                context_blocks) if context_blocks else "# No other interfaces defined."

            abs_path_str = str(
                self.project_manager.active_project_path / target_file) if self.project_manager.active_project_path else target_file

            # --- REVIEW AND REFINE LOOP ---
            max_retries = 3
            is_approved = False
            current_content = ""
            feedback_history = []

            for attempt in range(max_retries):
                # --- SELECT PROMPT AND AGENT ROLE FOR THIS ATTEMPT ---
                if attempt == 0:
                    agent_role_for_generation = "coder"
                    active_coder_prompt = CODER_PROMPT.format(
                        user_request=user_request, target_file=target_file, purpose=purpose, imports=imports,
                        public_members_specs=public_members_specs, interface_context=interface_context,
                        S_TIER_ENGINEERING_PROTOCOL=S_TIER_ENGINEERING_PROTOCOL,
                        RAW_CODE_OUTPUT_RULE=RAW_CODE_OUTPUT_RULE
                    )
                    self.event_bus.emit("agent_status_changed", "Coder",
                                        f"Generating {target_file} (Attempt 1)", "fa5s.code")
                else:
                    agent_role_for_generation = "reviewer" # ESCALATE to the smarter model
                    cumulative_feedback = "\n\n".join(feedback_history)
                    active_coder_prompt = CORRECTOR_PROMPT.format(
                        target_file=target_file, purpose=purpose, imports=imports,
                        public_members_specs=public_members_specs,
                        failed_code=current_content,
                        reviewer_feedback=cumulative_feedback,
                        S_TIER_ENGINEERING_PROTOCOL=S_TIER_ENGINEERING_PROTOCOL,
                        RAW_CODE_OUTPUT_RULE=RAW_CODE_OUTPUT_RULE
                    )
                    self.event_bus.emit("agent_status_changed", "Reviewer",
                                        f"Correcting {target_file} (Attempt {attempt + 1})", "fa5s.wrench")

                # --- STREAM GENERATION ---
                self.event_bus.emit("agent_activity_started", agent_role_for_generation.title(), abs_path_str)
                self.event_bus.emit("file_content_updated", target_file, "")
                await asyncio.sleep(0.1)

                full_streamed_content = ""
                async for chunk in self._stream_llm_agent_chunks(active_coder_prompt, agent_role_for_generation):
                    if chunk.startswith("LLM_API_ERROR:"):
                        self.log("error", f"Agent '{agent_role_for_generation}' failed for {target_file}: {chunk}")
                        full_streamed_content = None
                        break
                    self.event_bus.emit("stream_text_at_cursor", target_file, chunk)
                    full_streamed_content += chunk

                if full_streamed_content is None: break
                current_content = sanitize_llm_code_output(full_streamed_content)

                # --- REVIEW STEP ---
                self.event_bus.emit("agent_status_changed", "Reviewer", f"Reviewing {target_file}...", "fa5s.search")
                self.event_bus.emit("agent_activity_started", "Reviewer", abs_path_str)
                await asyncio.sleep(0.5)

                reviewer_prompt = REVIEWER_PROMPT.format(
                    target_file=target_file, purpose=purpose, imports=imports,
                    public_members_specs=public_members_specs, code_to_review=current_content,
                    S_TIER_ENGINEERING_PROTOCOL=S_TIER_ENGINEERING_PROTOCOL, JSON_OUTPUT_RULE=JSON_OUTPUT_RULE
                )

                review_response = await self._call_llm_agent(reviewer_prompt, "reviewer")
                review_json = self.validator.extract_and_parse_json(review_response)

                if review_json and review_json.get("approved") is True:
                    self.log("success", f"Reviewer approved '{target_file}' on attempt {attempt + 1}.")
                    is_approved = True
                    break

                feedback = "No specific feedback provided."
                if review_json and isinstance(review_json.get("feedback"), str) and review_json.get("feedback"):
                    feedback = review_json.get("feedback")

                self.log("warning", f"Reviewer rejected '{target_file}'. Feedback: {feedback}")
                feedback_history.append(f"--- Attempt {attempt + 1} Feedback ---\n{feedback}")

            if not is_approved:
                final_error_msg = f"FATAL: Could not produce an approved version of '{target_file}' after {max_retries} attempts. The generation process cannot continue reliably."
                self.log("error", final_error_msg)
                self.event_bus.emit("ai_response_ready", final_error_msg)
                self.event_bus.emit("ai_workflow_finished")
                return None

            if not current_content:
                final_error_msg = f"FATAL: Generation failed for {target_file}. No content was produced. Aborting workflow."
                self.log("error", final_error_msg)
                self.event_bus.emit("ai_response_ready", final_error_msg)
                self.event_bus.emit("ai_workflow_finished")
                return None

            # --- END REVIEW LOOP ---

            module_path = target_file.replace('/', '.').removesuffix('.py')
            fixed_content = self.import_fixer.fix_imports(current_content, project_index, module_path)

            new_symbols = self.indexer.get_symbols_from_content(fixed_content, module_path)
            project_index.update(new_symbols)

            final_code[target_file] = fixed_content
            self.event_bus.emit("finalize_editor_content", target_file)

            if fixed_content != current_content:
                self.event_bus.emit("file_content_updated", target_file, fixed_content)
            await asyncio.sleep(1.1)

        self.log("success", "✅ Ironclad Workflow Finished Successfully.")
        return final_code