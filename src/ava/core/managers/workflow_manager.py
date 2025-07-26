# src/ava/core/managers/workflow_manager.py
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Optional, Dict, TYPE_CHECKING, Any, List
from pathlib import Path

from src.ava.core.app_state import AppState
from src.ava.core.event_bus import EventBus
from src.ava.core.interaction_mode import InteractionMode
from src.ava.prompts import TEST_HEALER_PROMPT, RUNTIME_HEALER_PROMPT

if TYPE_CHECKING:
    from src.ava.core.managers.service_manager import ServiceManager
    from src.ava.core.managers.task_manager import TaskManager
    from src.ava.core.managers.window_manager import WindowManager
    from src.ava.services import ResponseValidatorService

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Orchestrates AI workflows based on the authoritative application state.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.service_manager: "ServiceManager" = None
        self.window_manager: "WindowManager" = None
        self.task_manager: "TaskManager" = None
        self._last_generated_code: Optional[Dict[str, str]] = None
        self._last_user_request: str = ""

    def set_managers(self, service_manager: "ServiceManager", window_manager: "WindowManager",
                     task_manager: "TaskManager"):
        self.service_manager = service_manager
        self.window_manager = window_manager
        self.task_manager = task_manager
        self.event_bus.subscribe("session_cleared", self._on_session_cleared)
        self.event_bus.subscribe("workflow_finalized", self._on_workflow_finalized)
        self.event_bus.subscribe("unit_test_generation_requested", self.handle_test_generation_request)
        self.event_bus.subscribe("test_file_generation_requested", self.handle_file_test_generation_request)
        self.event_bus.subscribe("heal_project_requested", self.handle_test_heal_request)
        self.event_bus.subscribe("run_program_and_heal_requested", self.handle_run_and_heal_request)

    def _on_workflow_finalized(self, final_code: Dict[str, str]):
        self._last_generated_code = final_code

    def _on_session_cleared(self):
        self._last_generated_code = None
        self._last_user_request = ""

    def _sanitize_code_output(self, raw_code: str) -> str:
        """Removes markdown fences and leading/trailing whitespace from LLM-generated code."""
        if raw_code.startswith("```python"):
            raw_code = raw_code[len("```python"):].strip()
        elif raw_code.startswith("```"):
            raw_code = raw_code[len("```"):].strip()
        if raw_code.endswith("```"):
            raw_code = raw_code[:-len("```")].strip()
        return raw_code

    async def _run_chat_workflow(self, user_idea: str, conversation_history: list):
        """Runs the simple chat workflow for the 'PLAN' mode."""
        self.log("info", f"Running simple chat for: '{user_idea[:50]}...'")
        llm_client = self.service_manager.get_llm_client()
        provider, model = llm_client.get_model_for_role("chat")
        if not provider or not model:
            self.event_bus.emit("streaming_chunk", "Sorry, no 'chat' model is configured.")
            return
        self.event_bus.emit("streaming_start", "Assistant")
        try:
            stream = llm_client.stream_chat(
                provider, model, user_idea, "chat", history=conversation_history
            )
            async for chunk in stream:
                self.event_bus.emit("streaming_chunk", chunk)
        finally:
            self.event_bus.emit("streaming_end")

    async def _run_build_workflow(self, user_request: str, existing_files: Optional[Dict[str, str]]):
        """Orchestrates the 'Blueprint -> Implement -> Review' assembly line."""
        self._last_user_request = user_request
        project_manager = self.service_manager.get_project_manager()
        coordinator = self.service_manager.get_generation_coordinator()
        final_code = await coordinator.coordinate_generation(existing_files, user_request)
        if not final_code:
            self.log("error", "Build workflow failed during code generation.")
            self.event_bus.emit("ai_response_ready", "Sorry, the code generation process failed.")
            return
        files_to_write = {k: v for k, v in final_code.items() if v is not None}
        files_to_delete = [k for k, v in final_code.items() if v is None]
        if project_manager and project_manager.git_manager:
            if files_to_write:
                project_manager.git_manager.write_and_stage_files(files_to_write)
            if files_to_delete:
                project_manager.delete_items(files_to_delete)
            commit_message = f"AI generation for: {user_request[:70]}"
            project_manager.git_manager.commit_staged_files(commit_message)
        self.event_bus.emit("workflow_finalized", final_code)
        self.log("success", "Build workflow completed successfully.")

    def handle_user_request(self, prompt: str, conversation_history: list,
                            image_bytes: Optional[bytes] = None, image_media_type: Optional[str] = None,
                            code_context: Optional[Dict[str, str]] = None):
        if not prompt.strip(): return
        app_state_service = self.service_manager.get_app_state_service()
        interaction_mode = app_state_service.get_interaction_mode()
        app_state = app_state_service.get_app_state()
        workflow_coroutine = None
        if interaction_mode == InteractionMode.PLAN:
            workflow_coroutine = self._run_chat_workflow(prompt, conversation_history)
        elif interaction_mode == InteractionMode.BUILD:
            existing_files = self.service_manager.get_project_manager().get_project_files() if app_state == AppState.MODIFY else None
            workflow_coroutine = self._run_build_workflow(prompt, existing_files)
        if workflow_coroutine:
            self.task_manager.start_ai_workflow_task(workflow_coroutine)

    def handle_test_generation_request(self, function_name: str, source_file_path_str: str):
        self.task_manager.start_ai_workflow_task(
            self._run_single_function_test_workflow(function_name, source_file_path_str)
        )

    async def _run_single_function_test_workflow(self, function_name: str, source_file_path_str: str):
        self.log("info", f"Test generation request received for function '{function_name}'.")
        test_generation_service = self.service_manager.get_test_generation_service()
        project_manager = self.service_manager.get_project_manager()
        extractor_service = self.service_manager.get_code_extractor_service()
        if not all([test_generation_service, project_manager, extractor_service, project_manager.active_project_path]):
            self.log("error", "Cannot generate test: Services or active project not available.")
            return
        source_file_path = Path(source_file_path_str)
        try:
            file_content = source_file_path.read_text(encoding='utf-8')
            function_code = extractor_service.extract_code_block(file_content, function_name)
            if not function_code:
                self.log("error", f"Code Extractor failed to find function '{function_name}'.")
                return
        except Exception as e:
            self.log("error", f"Failed to read or extract from source file: {e}")
            return
        relative_source_path = source_file_path.relative_to(project_manager.active_project_path).as_posix()
        generated_assets = await test_generation_service.generate_test_for_function(
            function_name, function_code, relative_source_path
        )
        await self._save_and_commit_test_assets(generated_assets, source_file_path, f"tests for {function_name}")

    def handle_file_test_generation_request(self, source_file_rel_path: str):
        self.task_manager.start_ai_workflow_task(
            self._run_full_file_test_workflow(source_file_rel_path)
        )

    async def _run_full_file_test_workflow(self, source_file_rel_path: str):
        self.log("info", f"Test generation request received for file '{source_file_rel_path}'.")
        project_manager = self.service_manager.get_project_manager()
        test_generation_service = self.service_manager.get_test_generation_service()
        if not all([test_generation_service, project_manager, project_manager.active_project_path]):
            self.log("error", "Cannot generate test file: Services or active project not available.")
            return
        source_file_abs_path = project_manager.active_project_path / source_file_rel_path
        try:
            file_content = source_file_abs_path.read_text(encoding='utf-8')
        except Exception as e:
            self.log("error", f"Failed to read source file '{source_file_abs_path.name}': {e}")
            return
        generated_assets = await test_generation_service.generate_tests_for_file(
            file_content, source_file_rel_path
        )
        await self._save_and_commit_test_assets(generated_assets, source_file_abs_path,
                                                f"tests for file {source_file_abs_path.name}")

    async def _save_and_commit_test_assets(self, generated_assets: Optional[Dict[str, str]], source_file_path: Path,
                                           commit_subject: str):
        project_manager = self.service_manager.get_project_manager()
        if not generated_assets or "test_code" not in generated_assets or not project_manager.active_project_path:
            self.log("error", f"Test generation failed for '{commit_subject}'.")
            return
        test_content = generated_assets["test_code"]
        requirements_content = generated_assets.get("requirements")
        source_filename = source_file_path.name
        test_filename = f"test_{source_filename}"
        test_file_rel_path = f"tests/{test_filename}"
        test_file_abs_path = project_manager.active_project_path / test_file_rel_path
        self.log("info", f"Saving generated test file to: {test_file_abs_path}")
        test_file_abs_path.parent.mkdir(parents=True, exist_ok=True)
        test_file_abs_path.write_text(test_content, encoding='utf-8')
        if project_manager.git_manager:
            project_manager.git_manager.stage_file(test_file_rel_path)
            if requirements_content:
                req_path = project_manager.active_project_path / "requirements.txt"
                current_reqs = req_path.read_text(encoding='utf-8') if req_path.exists() else ""
                new_reqs = set(current_reqs.splitlines())
                new_reqs.update(requirements_content.splitlines())
                req_path.write_text("\n".join(sorted(list(new_reqs))), encoding='utf-8')
                project_manager.git_manager.stage_file("requirements.txt")
            project_manager.git_manager.commit_staged_files(f"feat: Add {commit_subject}")
        self.event_bus.emit("file_content_updated", test_file_rel_path, test_content)
        self.event_bus.emit("test_file_generated", test_file_rel_path)

    def handle_test_heal_request(self):
        self.log("info", "Test-based Heal request received. Starting Heal workflow.")
        self.task_manager.start_ai_workflow_task(self._run_test_heal_workflow())

    def _find_failing_test_file(self, pytest_output: str) -> Optional[str]:
        match = re.search(r"(\S+\.py):\d+:", pytest_output)
        if match:
            try:
                path = Path(match.group(1))
                if path.is_absolute() and self.service_manager.project_manager.active_project_path:
                    return path.relative_to(self.service_manager.project_manager.active_project_path).as_posix()
                return path.as_posix()
            except ValueError:
                return match.group(1)
        return None

    async def _run_test_heal_workflow(self):
        self.event_bus.emit("agent_status_changed", "Healer", "Running project tests...", "fa5s.vial")
        execution_service = self.service_manager.get_execution_service()
        project_manager = self.service_manager.get_project_manager()
        exit_code, test_output = await execution_service.execute_and_capture("pytest")
        if exit_code == 0:
            self.log("success", "All tests passed! No healing needed.")
            self.event_bus.emit("agent_status_changed", "Healer", "All tests passed!", "fa5s.check-circle")
            return
        failing_file = self._find_failing_test_file(test_output)
        files_for_prompt = project_manager.get_project_files()
        if failing_file and failing_file in files_for_prompt:
            self.log("info", f"Redacting failing test file '{failing_file}' from Healer's context to prevent cheating.")
            files_for_prompt[failing_file] = "[This is the failing test file. Its content is locked and cannot be modified. You MUST fix the bug in the source code to make this test pass.]"
        await self._run_generic_heal_workflow(TEST_HEALER_PROMPT, {"test_output": test_output}, files_for_prompt)

    def handle_run_and_heal_request(self, command: str):
        self.log("info", f"Run & Heal request received for command: '{command}'")
        self.task_manager.start_ai_workflow_task(self._run_program_and_heal_workflow(command))

    async def _run_program_and_heal_workflow(self, command: str):
        execution_service = self.service_manager.get_execution_service()
        self.event_bus.emit("agent_status_changed", "Executor", f"Running '{command}'...", "fa5s.play")
        self.event_bus.emit("execute_command_requested", command)
        exit_code, runtime_output = await execution_service.execute_and_capture(command)
        if exit_code == 0:
            self.log("success", "Program ran successfully! No healing needed.")
            self.event_bus.emit("agent_status_changed", "Executor", "Run successful!", "fa5s.check-circle")
            return
        files_for_prompt = self.service_manager.get_project_manager().get_project_files()
        if "SyntaxError:" in runtime_output:
            self.log("warning", "SyntaxError detected. Attempting to fix syntax first.")
            await self._run_generic_heal_workflow(RUNTIME_HEALER_PROMPT, {"runtime_traceback": runtime_output}, files_for_prompt)
            self.event_bus.emit("terminal_output_received", "\n--- Syntax error fixed. Please try running the program again. ---")
            return
        if "ModuleNotFoundError" in runtime_output:
            self.log("info", "ModuleNotFoundError detected. Attempting to install dependencies.")
            self.event_bus.emit("terminal_output_received",
                                "\n--- Detected a missing library. Checking for requirements.txt... ---")
            requirements_path = self.service_manager.project_manager.active_project_path / "requirements.txt"
            if not requirements_path.exists():
                self.log("warning", "requirements.txt not found. Cannot automatically install dependencies.")
                self.event_bus.emit("terminal_output_received",
                                    "--- requirements.txt not found. Please create one or ask the AI to generate it. ---")
                return
            self.event_bus.emit("terminal_output_received", "--- Found requirements.txt. Attempting to install... ---")
            install_command = "pip install -r requirements.txt"
            install_exit_code, _ = await execution_service.execute_and_capture(install_command)
            if install_exit_code == 0:
                self.event_bus.emit("terminal_output_received",
                                    "\n--- Dependencies installed successfully. Please try running the program again. ---")
            else:
                self.event_bus.emit("terminal_output_received",
                                    "\n--- Failed to install dependencies. Please check the error log above. ---")
            return
        await self._run_generic_heal_workflow(RUNTIME_HEALER_PROMPT, {"runtime_traceback": runtime_output}, files_for_prompt)

    async def _run_generic_heal_workflow(self, prompt_template: str, context: Dict[str, str],
                                         files_for_prompt: Dict[str, str]):
        self.log("warning", "A failure was detected. Engaging Healer Agent.")
        self.event_bus.emit("agent_status_changed", "Healer", "Failure detected, attempting to fix...",
                            "fa5s.heartbeat")
        project_manager = self.service_manager.get_project_manager()
        llm_client = self.service_manager.get_llm_client()
        from src.ava.services import ResponseValidatorService
        validator = ResponseValidatorService()
        prompt_context = {
            "user_request": self._last_user_request or "The user's last request was to fix a failure.",
            "existing_files_json": json.dumps(files_for_prompt, indent=2),
            **context
        }
        healer_prompt = prompt_template.format(**prompt_context)
        healer_response_stream = llm_client.stream_chat(
            *llm_client.get_model_for_role("architect"), healer_prompt, "healer"
        )
        full_healer_response = "".join([chunk async for chunk in healer_response_stream])
        if not full_healer_response:
            self.log("error", "Healer agent returned an empty response. Aborting fix.")
            return
        rewritten_files = validator.extract_and_parse_json(full_healer_response)
        if not isinstance(rewritten_files, dict) or not rewritten_files:
            self.log("error", f"Healer failed to return a valid JSON fix. Response: {full_healer_response[:300]}")
            return
        self.log("success", f"Healer has provided a fix for {len(rewritten_files)} file(s). Applying changes...")
        final_code = project_manager.get_project_files().copy()
        for filename, new_content in rewritten_files.items():
            if filename not in final_code:
                self.log("warning", f"Healer tried to modify non-existent file: {filename}. Skipping.")
                continue
            sanitized_content = self._sanitize_code_output(new_content)
            if project_manager.active_project_path:
                abs_path_str = str(project_manager.active_project_path / filename)
                self.event_bus.emit("agent_activity_started", "Healer", abs_path_str)
            self.event_bus.emit("file_content_updated", filename, "")
            await asyncio.sleep(0.1)
            for char in sanitized_content:
                self.event_bus.emit("stream_text_at_cursor", filename, char)
                await asyncio.sleep(0.001)
            self.event_bus.emit("finalize_editor_content", filename)
            final_code[filename] = sanitized_content
            await asyncio.sleep(0.5)
        if project_manager.git_manager:
            sanitized_rewrites = {fname: self._sanitize_code_output(content) for fname, content in rewritten_files.items()}
            project_manager.git_manager.write_and_stage_files(sanitized_rewrites)
            project_manager.git_manager.commit_staged_files("fix: AI Healer applied automated fix")
        self.event_bus.emit("workflow_finalized", final_code)
        self.log("success", "✅ Healer workflow finished. Please review the fix and run again.")

    def log(self, level: str, message: str, **kwargs):
        self.event_bus.emit("log_message_received", "WorkflowManager", level, message, **kwargs)