# src/ava/core/managers/workflow_manager.py
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Dict, TYPE_CHECKING, Any, List

from src.ava.core.app_state import AppState
from src.ava.core.event_bus import EventBus
from src.ava.core.interaction_mode import InteractionMode

if TYPE_CHECKING:
    from src.ava.core.managers.service_manager import ServiceManager
    from src.ava.core.managers.task_manager import TaskManager
    from src.ava.core.managers.window_manager import WindowManager

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

    def set_managers(self, service_manager: "ServiceManager", window_manager: "WindowManager",
                     task_manager: "TaskManager"):
        self.service_manager = service_manager
        self.window_manager = window_manager
        self.task_manager = task_manager
        self.event_bus.subscribe("session_cleared", self._on_session_cleared)
        self.event_bus.subscribe("workflow_finalized", self._on_workflow_finalized)

    def _on_workflow_finalized(self, final_code: Dict[str, str]):
        self._last_generated_code = final_code

    def _on_session_cleared(self):
        self._last_generated_code = None

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
        project_manager = self.service_manager.get_project_manager()
        coordinator = self.service_manager.get_generation_coordinator()

        # The 'plan' step is removed. We go directly to the coordinator.
        final_code = await coordinator.coordinate_generation(existing_files, user_request)
        if not final_code:
            self.log("error", "Build workflow failed during code generation.")
            self.event_bus.emit("ai_response_ready", "Sorry, the code generation process failed.")
            return

        # 3. Finalization
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

    def log(self, level: str, message: str, **kwargs):
        self.event_bus.emit("log_message_received", "WorkflowManager", level, message, **kwargs)