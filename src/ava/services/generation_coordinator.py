# src/ava/services/generation_coordinator.py
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
from src.ava.prompts import (
    REVIEWER_PROMPT,
    SCAFFOLDER_PROMPT,
    COMPLETER_PROMPT,
    DEPENDENCY_ANALYZER_PROMPT,
)

logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """
    Implements the multi-stage 'Architect-Led Completion' strategy.

    This service orchestrates a sequential workflow for code generation:
    1.  Scaffolding: Creates the basic structure of files based on an architectural plan.
    2.  Dependency Analysis: Analyzes scaffolds to determine necessary imports and dependencies.
    3.  Code Completion: Fleshes out the scaffolds with complete, functional code.
    4.  Final Review: Performs static analysis and an LLM-based review to correct errors and
        ensure code quality.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus, context_manager: Any,
                 import_fixer_service: Any, integration_validator: Any, dependency_planner: Any):
        """
        Initializes the GenerationCoordinator.

        Args:
            service_manager (Any): The main service manager for accessing other services.
            event_bus (EventBus): The application's event bus for emitting events.
            context_manager (Any): Manages the context for generation tasks.
            import_fixer_service (Any): Service for fixing Python imports.
            integration_validator (Any): Service for validating integration between components.
            dependency_planner (Any): Service for analyzing code dependencies.
        """
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.context_manager = context_manager
        self.import_fixer_service = import_fixer_service
        self.integration_validator = integration_validator
        self.dependency_planner = dependency_planner
        self.llm_client = service_manager.get_llm_client()
        self.original_user_request = ""

    async def coordinate_architect_led_completion(self, whiteboard_plan: Dict[str, Any],
                                                  existing_files: Optional[Dict[str, str]],
                                                  user_request: str) -> Dict[str, str]:
        """
        Orchestrates the full 'Architect-Led Completion' generation workflow.

        Args:
            whiteboard_plan (Dict[str, Any]): The architectural plan from the Architect service.
            existing_files (Optional[Dict[str, str]]): A dictionary of existing file contents.
            user_request (str): The original user request that initiated the generation.

        Returns:
            Dict[str, str]: A dictionary of the generated and polished file contents.
        """
        try:
            self.original_user_request = user_request
            self.log("info", "🚀 Starting Architect-Led Completion workflow...")
            generated_files_this_session = (existing_files or {}).copy()
            tasks = whiteboard_plan.get("tasks", [])
            total_tasks = len(tasks)

            # --- STAGE 1: SCAFFOLDING (Architect) ---
            scaffolded_files = {}
            for i, task in enumerate(tasks):
                self.log("info", f"Architect is scaffolding task {i + 1}/{total_tasks}: {task.get('description')}")
                generated_files_this_session = await self._execute_scaffolding_task(
                    task, generated_files_this_session, whiteboard_plan
                )
                scaffolded_files[task.get("filename")] = generated_files_this_session[task.get("filename")]
                self.event_bus.emit("coordinated_generation_progress",
                                    {"filename": task.get('filename', 'Plan'), "completed": i + 1,
                                     "total": total_tasks})

            # --- STAGE 2: DEPENDENCY ANALYSIS (Dependency Analyst) ---
            self.log("info", "Scaffolding complete. Starting Dependency Analysis stage.")
            dependency_results = await self._perform_dependency_analysis(scaffolded_files, whiteboard_plan)

            # --- STAGE 3: CODE COMPLETION (Coder) ---
            self.log("info", "Dependency analysis complete. Starting Code Completion stage.")
            completed_files = {}
            for filename, scaffold_code in scaffolded_files.items():
                if not filename.endswith(".py"):
                    completed_files[filename] = scaffold_code
                    continue

                self.log("info", f"Coder is completing scaffold for: {filename}")
                file_dependency_info = dependency_results.get(filename, {})
                completed_code = await self._execute_completion_task(filename, scaffold_code, file_dependency_info)
                completed_files[filename] = completed_code

            # --- STAGE 4: FINAL REVIEW (Reviewer) ---
            self.log("info", "🔬 Starting final review pass with static analysis...")
            reviewed_files = await self._perform_final_review(completed_files)

            self.log("success", f"✅ Architect-Led Completion workflow finished. {len(reviewed_files)} files processed.")
            return reviewed_files

        except Exception as e:
            self.log("error", f"Coordinated generation failed: {e}")
            logger.exception("Exception in coordinate_architect_led_completion")
            return {}

    async def _execute_scaffolding_task(self, task: Dict[str, Any], current_files: Dict[str, str],
                                        whiteboard_plan: Dict[str, Any]) -> Dict[str, str]:
        filename = task.get("filename")
        if not filename:
            self.log("warning", f"Task '{task.get('description')}' has no filename. Skipping.")
            return current_files

        self.event_bus.emit("file_generation_starting", filename)
        await asyncio.sleep(0.1)

        self.event_bus.emit("agent_status_changed", "Architect", f"Scaffolding: {filename}", "fa5s.pencil-ruler")

        scaffold = await self._generate_scaffold_for_task(task, current_files, whiteboard_plan)
        if scaffold is None:
            scaffold = f"\n# ERROR: Failed to generate scaffold for task: {task.get('description')}\n"

        await self._stream_content(filename, scaffold, clear_first=True)

        current_files[filename] = scaffold
        return current_files

    async def _generate_scaffold_for_task(self, task: Dict[str, Any], current_files: Dict[str, str],
                                          whiteboard_plan: Dict[str, Any]) -> Optional[str]:
        prompt = self._build_scaffold_generation_prompt(task, current_files, whiteboard_plan)
        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            self.log("error", f"No model for 'architect' role. Cannot generate scaffold for {task.get('filename')}.")
            return None

        scaffold = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "architect"):
                scaffold += chunk
            return self.robust_clean_llm_output(scaffold)
        except Exception as e:
            self.log("error", f"LLM scaffold generation failed for {task.get('filename')}: {e}")
            logger.exception("Exception in _generate_scaffold_for_task")
            return None

    def _build_scaffold_generation_prompt(self, task: Dict[str, Any], current_files: Dict[str, str],
                                          whiteboard_plan: Dict[str, Any]) -> str:
        filename = task.get("filename")
        other_files_context = {k: v for k, v in current_files.items() if k != filename}
        return SCAFFOLDER_PROMPT.format(
            whiteboard_plan_json=json.dumps(whiteboard_plan, indent=2),
            task_json=json.dumps(task, indent=2),
            filename=filename,
            code_context_json=json.dumps(other_files_context, indent=2)
        )

    async def _perform_dependency_analysis(self, scaffolded_files: Dict[str, str],
                                           whiteboard_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes the scaffolded code to identify dependencies using an LLM.

        Args:
            scaffolded_files (Dict[str, str]): The generated scaffold code for each file.
            whiteboard_plan (Dict[str, Any]): The overall architectural plan.

        Returns:
            Dict[str, Any]: A dictionary where keys are filenames and values are the
                            dependency analysis results for that file.
        """
        self.event_bus.emit("agent_status_changed", "Dep. Analyst", "Analyzing code dependencies...", "fa5s.project-diagram")
        self.log("info", "Analyzing dependencies for scaffolded files...")

        project_symbols = self.context_manager.get_project_symbol_index()
        prompt = DEPENDENCY_ANALYZER_PROMPT.format(
            whiteboard_plan_json=json.dumps(whiteboard_plan, indent=2),
            scaffolded_files_json=json.dumps(scaffolded_files, indent=2),
            project_symbols_json=json.dumps(project_symbols, indent=2)
        )

        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            self.log("error", "No model for 'architect' role. Cannot perform dependency analysis.")
            return {}

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "architect"):
                raw_response += chunk

            analysis_result = self.robust_parse_json_response(raw_response)
            if not analysis_result or "dependencies" not in analysis_result:
                self.log("warning", "Dependency analysis did not return a valid structure. Proceeding without it.")
                return {}

            self.log("success", f"Dependency analysis complete. Found dependencies for {len(analysis_result.get('dependencies', []))} files.")
            return {item['filename']: item for item in analysis_result.get('dependencies', []) if 'filename' in item}
        except Exception as e:
            self.log("error", f"Dependency analysis pass failed: {e}")
            logger.exception("Exception in _perform_dependency_analysis")
            return {}

    async def _execute_completion_task(self, filename: str, scaffold_code: str, dependency_info: Dict[str, Any]) -> str:
        """
        Executes the code completion task for a single file.

        Args:
            filename (str): The name of the file to complete.
            scaffold_code (str): The scaffold code to be completed.
            dependency_info (Dict[str, Any]): The dependency analysis results for this file.

        Returns:
            str: The completed code.
        """
        self.event_bus.emit("agent_status_changed", "Coder", f"Completing: {filename}", "fa5s.code")

        completed_code = await self._generate_completed_code(scaffold_code, dependency_info)
        if completed_code is None:
            self.log("error", f"Code completion failed for {filename}. Returning original scaffold.")
            return scaffold_code

        await self._stream_content(filename, completed_code, clear_first=True)
        return completed_code

    async def _generate_completed_code(self, scaffold_code: str, dependency_info: Dict[str, Any]) -> Optional[str]:
        """
        Calls the LLM to generate the full code from a scaffold and dependency info.

        Args:
            scaffold_code (str): The scaffold code.
            dependency_info (Dict[str, Any]): The dependency analysis results.

        Returns:
            Optional[str]: The generated code as a string, or None on failure.
        """
        prompt = COMPLETER_PROMPT.format(
            scaffold_code=scaffold_code,
            dependency_info_json=json.dumps(dependency_info, indent=2)
        )
        provider, model = self.llm_client.get_model_for_role("coder")
        if not provider or not model:
            self.log("error", "No model for 'coder' role. Cannot complete scaffold.")
            return None

        completed_code = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "coder"):
                completed_code += chunk
            return self.robust_clean_llm_output(completed_code)
        except Exception as e:
            self.log("error", f"LLM code completion failed: {e}")
            logger.exception("Exception in _generate_completed_code")
            return None

    async def _perform_final_review(self, completed_files: Dict[str, str]) -> Dict[str, str]:
        """
        Performs a final review pass using static analysis and an LLM to find and fix issues.

        Args:
            completed_files (Dict[str, str]): The generated code to be reviewed.

        Returns:
            Dict[str, str]: The code after applying review corrections.
        """
        project_manager = self.service_manager.get_project_manager()
        lsp_client = self.service_manager.get_lsp_client_service()
        if not project_manager or not project_manager.active_project_path or not lsp_client:
            self.log("warning", "Skipping final review: Project or LSP client not available.")
            return completed_files

        self.log("info", "Saving generated files to disk for static analysis...")
        project_manager.git_manager.write_and_stage_files(completed_files)

        self.event_bus.emit("agent_status_changed", "LSP", "Running static analysis...", "fa5s.cogs")
        diagnostics = await self._collect_lsp_diagnostics(completed_files)
        self.log("success", f"Static analysis complete. Found {len(diagnostics)} issues.")
        diagnostics_json = json.dumps(diagnostics, indent=2)

        self.event_bus.emit("agent_status_changed", "Reviewer", "Analyzing code with diagnostics...", "fa5s.search")
        prompt = REVIEWER_PROMPT.format(
            user_request=self.original_user_request,
            lsp_diagnostics_json=diagnostics_json,
            code_to_review_json=json.dumps(completed_files, indent=2)
        )
        provider, model = self.llm_client.get_model_for_role("reviewer")
        if not provider or not model:
            self.log("error", "No model for 'reviewer' role. Skipping review pass.")
            return completed_files

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "reviewer"):
                raw_response += chunk

            review_result = self.robust_parse_json_response(raw_response)
            if not review_result or not review_result.get("issues"):
                self.log("success", "✅ Final review complete. No issues found.")
                return completed_files

            self.log("warning", f"Review found {len(review_result['issues'])} issues. Applying fixes...")
            self.event_bus.emit("agent_status_changed", "Surgeon", "Applying review fixes...", "fa5s.cut")
            corrected_files = completed_files.copy()
            for issue in review_result["issues"]:
                filename, code = issue.get("filename"), issue.get("corrected_code")
                start, end = issue.get("start_line"), issue.get("end_line")
                if not all([filename, code is not None, isinstance(start, int), isinstance(end, int)]):
                    continue
                if filename not in corrected_files:
                    continue
                try:
                    self.log("info", f"Applying fix to {filename}: {issue.get('description')}")
                    lines = corrected_files[filename].splitlines(True)
                    start_idx, end_idx = max(0, start - 1), min(len(lines), end)
                    if not code.endswith('\n'):
                        code += '\n'
                    new_lines = lines[:start_idx] + code.splitlines(True) + lines[end_idx:]
                    corrected_files[filename] = "".join(new_lines)
                    await self._stream_content(filename, corrected_files[filename], clear_first=True)
                except Exception as e:
                    self.log("error", f"Failed to apply review fix to {filename}: {e}")
            return corrected_files
        except Exception as e:
            self.log("error", f"Final Review pass failed: {e}")
            logger.exception("Exception in _perform_final_review")
            return completed_files

    async def _collect_lsp_diagnostics(self, generated_files: Dict[str, str]) -> Dict[str, List[Dict]]:
        lsp_client = self.service_manager.get_lsp_client_service()
        project_manager = self.service_manager.get_project_manager()
        diagnostics_results = {}
        analysis_complete = asyncio.Event()

        py_files_to_analyze = {f for f in generated_files if f.endswith('.py')}
        if not py_files_to_analyze:
            return {}

        async def on_diagnostic(uri: str, diagnostics: List[Dict]):
            try:
                file_path = Path(uri.replace("file:///", "").replace("%3A", ":")).resolve()
                rel_path = file_path.relative_to(project_manager.active_project_path.resolve()).as_posix()
                if rel_path in py_files_to_analyze:
                    diagnostics_results[rel_path] = [
                        {'source': d.get('source', 'linter'), 'message': d.get('message', '')} for d in diagnostics
                    ]
                    if diagnostics_results.keys() == py_files_to_analyze:
                        analysis_complete.set()
            except (ValueError, KeyError):
                pass

        self.event_bus.subscribe("lsp_diagnostics_received", on_diagnostic)

        for filename, content in generated_files.items():
            if filename.endswith('.py'):
                full_path = str(project_manager.active_project_path / filename)
                await lsp_client.did_open(full_path, content)

        try:
            await asyncio.wait_for(analysis_complete.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            self.log("warning", "LSP diagnostic collection timed out. Proceeding with partial data.")

        self.event_bus.unsubscribe("lsp_diagnostics_received", on_diagnostic)
        return diagnostics_results

    async def _stream_content(self, filename: str, content: str, clear_first: bool = False):
        if clear_first:
            self.event_bus.emit("stream_code_chunk", filename, "")
            await asyncio.sleep(0.1)
        chunk_size = 50
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            self.event_bus.emit("stream_code_chunk", filename, chunk)
            await asyncio.sleep(0.01)

    def robust_clean_llm_output(self, content: str) -> str:
        content = content.strip()
        code_block_regex = re.compile(r'```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```', re.DOTALL)
        matches = code_block_regex.findall(content)
        if matches:
            return "\n".join(m.strip() for m in matches)
        return content

    def robust_parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        match = re.search(r'\{.*}', response, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def log(self, level: str, message: str, details: str = ""):
        full_message = f"{message}\nDetails: {details}" if details else message
        self.event_bus.emit("log_message_received", "GenerationCoordinator", level, full_message)