# src/ava/core/managers/workflow_manager.py
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Dict, TYPE_CHECKING, Any, List
from pathlib import Path

from src.ava.core.app_state import AppState
from src.ava.core.event_bus import EventBus
from src.ava.core.interaction_mode import InteractionMode
from src.ava.prompts import HEALER_PROMPT

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
        self.event_bus.subscribe("heal_project_requested", self.handle_heal_request)

    def _on_workflow_finalized(self, final_code: Dict[str, str]):
        self._last_generated_code = final_code

    def _on_session_cleared(self):
        self._last_generated_code = None
        self._last_user_request = ""

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
        self._last_user_request = user_request  # Store for healer
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
                            image_bytes: Optional[bytes] = None,
                            image_media_type: Optional[str] = None,
                            code_context: Optional[Dict[str, str]] = None):
        """The central router for all user chat input."""
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

    async def handle_test_generation_request(self, function_name: str, source_file_path_str: str):
        """Handles the request from the UI to generate a unit test for a function."""
        self.log("info", f"Test generation request received for '{function_name}'.")
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
                self.log("error",
                         f"Code Extractor failed to find function '{function_name}' in '{source_file_path.name}'.")
                self.event_bus.emit("ai_workflow_finished")
                return
        except Exception as e:
            self.log("error", f"Failed to read or extract from source file: {e}")
            self.event_bus.emit("ai_workflow_finished")
            return

        relative_source_path = source_file_path.relative_to(project_manager.active_project_path).as_posix()

        # This will now return a dictionary with the test code and requirements
        generated_assets = await test_generation_service.generate_test_for_function(
            function_name, function_code, relative_source_path
        )

        if not generated_assets or "test_code" not in generated_assets:
            self.log("error", f"Test generation failed for function '{function_name}'.")
            self.event_bus.emit("ai_workflow_finished")
            return

        test_content = generated_assets["test_code"]
        requirements_content = generated_assets.get("requirements")

        # Determine the path for the new test file
        source_filename = source_file_path.name
        test_filename = f"test_{source_filename}"
        test_file_rel_path = f"tests/{test_filename}"
        test_file_abs_path = project_manager.active_project_path / test_file_rel_path

        self.log("info", f"Saving generated test file to: {test_file_abs_path}")
        test_file_abs_path.parent.mkdir(parents=True, exist_ok=True)
        test_file_abs_path.write_text(test_content, encoding='utf-8')

        if project_manager.git_manager:
            project_manager.git_manager.stage_file(test_file_rel_path)

            # Write and stage requirements.txt if content is available
            if requirements_content:
                req_path = project_manager.active_project_path / "requirements.txt"
                req_path.write_text(requirements_content, encoding='utf-8')
                project_manager.git_manager.stage_file("requirements.txt")

            project_manager.git_manager.commit_staged_files(f"feat: Add unit tests for {function_name}")

        self.event_bus.emit("file_content_updated", test_file_rel_path, test_content)
        self.event_bus.emit("test_file_generated", test_file_rel_path)
        self.event_bus.emit("ai_workflow_finished")

    def handle_heal_request(self):
        """Handles the 'Run Tests & Heal' request from the UI."""
        self.log("info", "Heal request received. Starting Heal workflow.")
        self.task_manager.start_ai_workflow_task(self._run_heal_workflow())

    async def _run_heal_workflow(self):
        """The core logic for the self-healing workflow."""
        execution_service = self.service_manager.get_execution_service()
        project_manager = self.service_manager.get_project_manager()
        llm_client = self.service_manager.get_llm_client()

        from src.ava.services import ResponseValidatorService
        validator = ResponseValidatorService()

        if not all([execution_service, project_manager, llm_client]):
            self.log("error", "Heal workflow cannot run: missing core services.")
            return

        self.event_bus.emit("agent_status_changed", "Healer", "Running project tests...", "fa5s.vial")

        exit_code, test_output = await execution_service.execute_and_capture("pytest")

        if exit_code == 0:
            self.log("success", "All tests passed! No healing needed.")
            self.event_bus.emit("agent_status_changed", "Healer", "All tests passed!", "fa5s.check-circle")
            self.event_bus.emit("ai_workflow_finished")
            return

        self.log("warning", "Tests failed. Engaging Healer Agent.")
        self.event_bus.emit("agent_status_changed", "Healer", "Tests failed, attempting to fix...", "fa5s.heartbeat")

        existing_files = project_manager.get_project_files()
        healer_prompt = HEALER_PROMPT.format(
            user_request=self._last_user_request or "The user's last request was to fix test failures.",
            test_output=test_output,
            existing_files_json=json.dumps(existing_files, indent=2)
        )

        # --- THE FIX for TypeError ---
        # Get the async generator first
        healer_response_stream = llm_client.stream_chat(
            *llm_client.get_model_for_role("architect"),
            healer_prompt, "healer"
        )

        # Then iterate over it with async for
        full_healer_response = ""
        async for chunk in healer_response_stream:
            full_healer_response += chunk
        # --- END OF FIX ---

        if not full_healer_response:
            self.log("error", "Healer agent returned an empty response. Aborting fix.")
            self.event_bus.emit("ai_workflow_finished")
            return

        rewritten_files = validator.extract_and_parse_json(full_healer_response)

        if not isinstance(rewritten_files, dict) or not rewritten_files:
            self.log("error", f"Healer agent failed to return a valid JSON fix. Response: {full_healer_response[:300]}")
            self.event_bus.emit("ai_workflow_finished")
            return

        self.log("success", f"Healer agent has provided a fix for {len(rewritten_files)} file(s). Applying changes...")

        final_code = existing_files.copy()
        for filename, new_content in rewritten_files.items():
            if filename not in final_code:
                self.log("warning", f"Healer tried to modify a non-existent file: {filename}. Skipping.")
                continue

            if project_manager.active_project_path:
                abs_path_str = str(project_manager.active_project_path / filename)
                self.event_bus.emit("agent_activity_started", "Healer", abs_path_str)

            self.event_bus.emit("file_content_updated", filename, "")
            await asyncio.sleep(0.1)
            for char in new_content:
                self.event_bus.emit("stream_text_at_cursor", filename, char)
                await asyncio.sleep(0.001)

            self.event_bus.emit("finalize_editor_content", filename)
            final_code[filename] = new_content
            await asyncio.sleep(0.5)

        if project_manager.git_manager:
            project_manager.git_manager.write_and_stage_files(rewritten_files)
            project_manager.git_manager.commit_staged_files("fix: AI Healer applied fix for test failures")

        self.event_bus.emit("workflow_finalized", final_code)
        self.log("success", "✅ Healer workflow finished. Please review the fix and run tests again.")
        self.event_bus.emit("ai_workflow_finished")

    def log(self, level: str, message: str, **kwargs):
        self.event_bus.emit("log_message_received", "WorkflowManager", level, message, **kwargs)