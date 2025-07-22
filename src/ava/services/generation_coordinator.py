# src/ava/services/generation_coordinator.py
import asyncio
import json
import logging
import re
import ast
from typing import Dict, Any, Optional, List, Tuple

from src.ava.core.event_bus import EventBus
from src.ava.prompts import ARCHITECT_SCAFFOLD_PROMPT, CODER_FILL_PROMPT

logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """
    Orchestrates the new "Serial Scaffolding" workflow.
    Phase 1: Architect builds the project skeleton.
    Phase 2: Coders fill in function bodies serially.
    Phase 3: Architect performs a final review.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = service_manager.get_llm_client()
        self.original_user_request = ""
        self.original_plan = {}

    async def coordinate_generation(
            self,
            plan: Dict[str, Any],
            existing_files: Optional[Dict[str, str]],
            user_request: str,
    ) -> Optional[Dict[str, str]]:
        """Executes the new three-phase generation pipeline."""
        self.original_user_request = user_request
        self.original_plan = plan

        # --- PHASE 1: ARCHITECT BUILDS THE SCAFFOLD ---
        scaffold_files = await self._execute_scaffold_phase()
        if not scaffold_files:
            self.log("error", "Scaffolding phase failed. Aborting generation.")
            return None

        # --- PHASE 2: CODERS FILL THE SCAFFOLD SERIALLY ---
        implemented_files = await self._execute_fill_phase(scaffold_files)
        if not implemented_files:
            self.log("error", "Implementation phase failed. Aborting generation.")
            return None

        # --- PHASE 3: ARCHITECT REVIEWS THE FINAL PRODUCT ---
        reviewed_files = await self._execute_review_stage(implemented_files)
        if reviewed_files is None:
            self.log("warning", "Review stage failed. Returning implemented code as-is.")
            return implemented_files

        self.log("success", "✅ Scaffolding Workflow Finished Successfully.")
        return reviewed_files

    async def _execute_scaffold_phase(self) -> Optional[Dict[str, str]]:
        """Calls the Architect to generate the empty project skeleton."""
        self.log("info", "--- Phase 1: Architect is building the project skeleton... ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Designing project skeleton...",
                            "fa5s.drafting-compass")

        prompt = ARCHITECT_SCAFFOLD_PROMPT.format(user_request=self.original_user_request)
        scaffold_json = await self._call_architect_llm(prompt)

        if not scaffold_json or not isinstance(scaffold_json, dict):
            self.log("error", "Architect failed to return a valid JSON object for the scaffold.")
            return None

        self.event_bus.emit("project_scaffold_generated", scaffold_json)
        await asyncio.sleep(0.5)
        return scaffold_json

    async def _execute_fill_phase(self, scaffold_files: Dict[str, str]) -> Optional[Dict[str, str]]:
        """Parses the scaffold and calls Coders serially to fill function bodies."""
        self.log("info", "--- Phase 2: Coder agents deploying serially... ---")

        tasks_to_fill = self._find_functions_to_fill(scaffold_files)
        if not tasks_to_fill:
            self.log("warning", "No functions with 'pass' found to be filled in the scaffold.")
            return scaffold_files

        project_scaffold_json = json.dumps(scaffold_files, indent=2)
        implemented_code = scaffold_files.copy()

        for i, (filename, func_def) in enumerate(tasks_to_fill):
            self.log("info",
                     f"Coder starting task ({i + 1}/{len(tasks_to_fill)}): Implement {func_def['name']} in {filename}")
            self.event_bus.emit("agent_status_changed", "Coder",
                                f"({i + 1}/{len(tasks_to_fill)}) Implementing {func_def['name']}", "fa5s.code")

            prompt = CODER_FILL_PROMPT.format(
                project_scaffold=project_scaffold_json,
                filename=filename,
                function_signature=func_def['signature'],
                function_description=func_def['description']
            )
            function_body = await self._call_llm_agent(prompt, "coder")

            if function_body:
                # Indent the new body to match the function's indentation level
                indentation = ' ' * func_def['col_offset']
                indented_body = "\n".join([f"{indentation}{line}" for line in function_body.splitlines()])

                # Robustly replace the 'pass' statement
                original_function_text = func_def['full_text']
                pass_statement = f"{' ' * func_def['col_offset']}pass"
                new_function_text = original_function_text.replace(pass_statement, indented_body, 1)

                implemented_code[filename] = implemented_code[filename].replace(original_function_text,
                                                                                new_function_text)

                self.event_bus.emit("file_content_updated", filename, implemented_code[filename])
                await asyncio.sleep(0.2)  # Stagger UI updates
            else:
                self.log("warning",
                         f"Coder failed to provide a body for {func_def['name']} in {filename}. 'pass' will be kept.")

        return implemented_code

    def _find_functions_to_fill(self, scaffold_files: Dict[str, str]) -> List[Tuple[str, Dict[str, Any]]]:
        """Uses AST to find functions with only a 'pass' statement."""
        fill_tasks = []
        plan_tasks_by_file = {task['filename']: task for task in self.original_plan.get("tasks", [])}

        for filename, content in scaffold_files.items():
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                            task_info = plan_tasks_by_file.get(filename, {})
                            func_def = {
                                "name": node.name,
                                "signature": ast.get_source_segment(content, node).split(':\n')[0],
                                "description": task_info.get("description", f"Implement the {node.name} function."),
                                "full_text": ast.get_source_segment(content, node),
                                "col_offset": node.body[0].col_offset
                            }
                            fill_tasks.append((filename, func_def))
            except Exception as e:
                self.log("error", f"Failed to parse scaffold file {filename}: {e}")
        return fill_tasks

    async def _execute_review_stage(self, files_to_review: Dict) -> Optional[Dict]:
        """The existing review stage, now acting as a final check."""
        self.log("info", "--- Phase 3: Architect is performing final integration review... ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Final review...", "fa5s.search")

        architect = self.service_manager.get_architect_service()
        fixes_plan = await architect.review_and_fix(self.original_user_request, json.dumps(files_to_review, indent=2))

        if fixes_plan is None:
            self.log("warning", "Reviewer agent failed to return valid JSON. Skipping review.")
            return files_to_review

        if fixes := fixes_plan.get("fixes"):
            self.log("info", f"Architect found {len(fixes)} issues. Applying final fixes...")
            return await self._apply_animated_surgical_edits(files_to_review, fixes)

        self.log("success", "Architect review complete. No issues found.")
        return files_to_review

    async def _apply_animated_surgical_edits(self, original_files: Dict, edits: List[Dict]) -> Dict:
        """Applies fixes with the slick UI animation."""
        modified_files = original_files.copy()
        for edit in edits:
            filename = edit.get("filename")
            start = edit.get("start_line")
            end = edit.get("end_line")
            corrected_code = edit.get("corrected_code")

            if not all([filename, start, end, corrected_code is not None]):
                self.log("warning", f"Reviewer provided an incomplete fix and it was discarded: {edit}")
                continue

            if filename not in modified_files:
                self.log("warning", f"Reviewer tried to edit non-existent file: {filename}")
                continue

            self.event_bus.emit("highlight_lines_for_edit", filename, start, end)
            await asyncio.sleep(0.75)
            self.event_bus.emit("delete_highlighted_lines", filename)
            await asyncio.sleep(0.4)

            # After deletion, we need to update the in-memory content
            lines = modified_files[filename].splitlines()
            del lines[start - 1:end]

            # Insert new code at the correct position
            lines[start - 1:start - 1] = corrected_code.splitlines()
            final_content = "\n".join(lines)
            modified_files[filename] = final_content
            self.event_bus.emit("file_content_updated", filename, final_content)
            await asyncio.sleep(0.2)

        return modified_files

    async def _call_architect_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Helper to call the architect and parse its JSON response."""
        raw_response = await self._call_llm_agent(prompt, "architect", stream=False)
        if not raw_response: return None
        try:
            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if not match: raise ValueError("No JSON object found in Architect's response.")
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError) as e:
            self.log("error", f"Architect response was not valid JSON: {e}\nResponse: {raw_response[:500]}")
            return None

    async def _call_llm_agent(self, prompt: str, role: str, stream: bool = True) -> Optional[str]:
        """Generic LLM call helper."""
        provider, model = self.llm_client.get_model_for_role(role)
        if not provider or not model:
            self.log("error", f"No model configured for role '{role}'");
            return None

        response_content = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, role):
                response_content += chunk

            if role == "coder":
                match = re.search(r"```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```", response_content, re.DOTALL)
                return match.group(1).strip() if match else response_content.strip()
            return response_content
        except Exception as e:
            self.log("error", f"Error from LLM for role '{role}': {e}", exc_info=True);
            return None

    def log(self, level: str, message: str, **kwargs):
        self.event_bus.emit("log_message_received", "GenCoordinator", level, message, **kwargs)