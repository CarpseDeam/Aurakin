# src/ava/core/managers/workflow_manager.py
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.ava.core.app_state import AppState
from src.ava.core.event_bus import EventBus
from src.ava.core.interaction_mode import InteractionMode
from src.ava.prompts import AURA_REFINEMENT_PROMPT, CREATIVE_ASSISTANT_PROMPT


class WorkflowManager:
    """
    Orchestrates AI workflows based on the authoritative application state.
    It reads state from AppStateService but does not set it.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.service_manager: "ServiceManager" = None
        self.window_manager: "WindowManager" = None
        self.task_manager: "TaskManager" = None
        self._last_generated_code: Optional[Dict[str, str]] = None
        self._is_plugin_override_active = False  # Retained for potential future Python plugins
        print("[WorkflowManager] Initialized")

    def set_managers(self, service_manager: "ServiceManager", window_manager: "WindowManager",
                     task_manager: "TaskManager"):
        """Set references to other managers and subscribe to relevant events."""
        self.service_manager = service_manager
        self.window_manager = window_manager
        self.task_manager = task_manager
        self.event_bus.subscribe("review_and_fix_from_plugin_requested", self.handle_review_and_fix_request)
        self.event_bus.subscribe("session_cleared", self._on_session_cleared)
        # CHANGE: Subscribe to the new 'workflow_finalized' event for Aura's context
        self.event_bus.subscribe("workflow_finalized", self._on_workflow_finalized)
        self.event_bus.subscribe("plugin_build_override_activated", self._activate_plugin_override)

    def _activate_plugin_override(self):
        """Called by a plugin to signal it's taking over the build process."""
        self._is_plugin_override_active = True

    # CHANGE: Rename method and parameter for clarity
    def _on_workflow_finalized(self, final_code: Dict[str, str]):
        """Catches the final code after a build to be used by Aura."""
        self.log("info", f"WorkflowManager captured {len(final_code)} final files for Aura's context.")
        self._last_generated_code = final_code
        self._is_plugin_override_active = False  # Reset override after a build completes

    async def _run_aura_workflow(self, user_idea: str, conversation_history: list, image_bytes: Optional[bytes],
                                 image_media_type: Optional[str]):
        """Runs the Aura persona workflow."""
        self.log("info", f"Aura is processing: '{user_idea[:50]}...'")

        history_for_prompt = conversation_history[:-1] if conversation_history else []
        formatted_history = "\n".join(
            [f"{msg.get('sender', msg.get('role', 'unknown')).title()}: {msg.get('text', '') or msg.get('content', '')}"
             for msg in history_for_prompt]
        )

        if self._last_generated_code:
            self.log("info", "Aura is in REFINEMENT mode with existing code context.")
            code_context_json = json.dumps(self._last_generated_code, indent=2)
            aura_prompt = AURA_REFINEMENT_PROMPT.format(
                conversation_history=formatted_history,
                user_idea=user_idea,
                code_context=code_context_json
            )
        else:
            self.log("info", "Aura is in CREATION mode.")
            aura_prompt = CREATIVE_ASSISTANT_PROMPT.format(
                conversation_history=formatted_history,
                user_idea=user_idea
            )

        llm_client = self.service_manager.get_llm_client()
        provider, model = llm_client.get_model_for_role("chat")

        if not provider or not model:
            self.event_bus.emit("streaming_chunk", "Sorry, no 'chat' model is configured for Aura.")
            return

        self.event_bus.emit("streaming_start", "Aura")
        try:
            stream = llm_client.stream_chat(
                provider, model, aura_prompt, "chat",
                image_bytes, image_media_type,
                history=conversation_history
            )
            async for chunk in stream:
                self.event_bus.emit("streaming_chunk", chunk)
        except Exception as e:
            self.event_bus.emit("streaming_chunk", f"\n\nAura encountered an error: {e}")
            self.log("error", f"Error during Aura streaming: {e}")
        finally:
            self.event_bus.emit("streaming_end")

    async def _run_build_workflow(self, prompt: str, existing_files: Optional[Dict[str, str]]):
        """
        Orchestrates the entire build process from planning to final code generation.
        """
        architect_service = self.service_manager.get_architect_service()
        coordinator = self.service_manager.get_generation_coordinator()
        project_manager = self.service_manager.get_project_manager()

        # 1. Get the plan from the Architect
        whiteboard_plan = await architect_service.create_whiteboard_plan(prompt, existing_files)
        if not whiteboard_plan or not whiteboard_plan.get("tasks"):
            self.log("error", "Build workflow failed: Could not create a valid plan.")
            self.event_bus.emit("ai_response_ready", "Sorry, I couldn't create a plan for that request.")
            return

        # --- THIS IS THE FIX ---
        # For new projects, ensure .gitignore is part of the plan so the visualizer sees it.
        is_new_project = not existing_files
        if is_new_project:
            tasks = whiteboard_plan.get("tasks", [])
            has_gitignore = any(task.get("filename") == ".gitignore" for task in tasks)
            if not has_gitignore:
                tasks.append({
                    "type": "create_file",
                    "filename": ".gitignore",
                    "description": "Standard git ignore file for Python projects."
                })
                whiteboard_plan["tasks"] = tasks
                self.log("info", "Injected .gitignore into the build plan for new project visualization.")
        # --- END FIX ---

        # 2. Execute the plan with the Coordinator using the new method name
        final_code = await coordinator.coordinate_architect_led_completion(whiteboard_plan, existing_files, prompt)
        if not final_code:
            self.log("error", "Build workflow failed: Code generation returned no files.")
            self.event_bus.emit("ai_response_ready", "Sorry, the code generation failed unexpectedly.")
            return

        # 3. Finalize: save files and notify the UI
        if project_manager and project_manager.git_manager:
            self.log("info", "Build complete. Writing and staging files.")
            project_manager.git_manager.write_and_stage_files(final_code)
            commit_message = f"AI generation based on prompt: {prompt[:80]}"
            project_manager.git_manager.commit_staged_files(commit_message)

        # CHANGE: Emit the new 'workflow_finalized' event.
        # This is the single source of truth that the entire process is complete.
        self.event_bus.emit("workflow_finalized", final_code)

    def handle_user_request(self, prompt: str, conversation_history: list,
                            image_bytes: Optional[bytes] = None, image_media_type: Optional[str] = None,
                            code_context: Optional[Dict[str, str]] = None):
        """The central router for all user chat input."""
        stripped_prompt = prompt.strip()
        if not stripped_prompt and not image_bytes and not code_context:
            return

        app_state_service = self.service_manager.get_app_state_service()
        if not app_state_service:
            self.log("error", "AppStateService not available.")
            return

        interaction_mode = app_state_service.get_interaction_mode()
        app_state = app_state_service.get_app_state()

        workflow_coroutine = None
        if interaction_mode == InteractionMode.PLAN:
            workflow_coroutine = self._run_aura_workflow(prompt, conversation_history, image_bytes, image_media_type)
        elif interaction_mode == InteractionMode.BUILD:
            if app_state == AppState.BOOTSTRAP:
                self._last_generated_code = None
                workflow_coroutine = self._run_build_workflow(prompt, existing_files=None)
            elif app_state == AppState.MODIFY:
                existing_files = self.service_manager.get_project_manager().get_project_files()
                workflow_coroutine = self._run_build_workflow(prompt, existing_files)
        else:
            self.log("error", f"Unknown interaction mode: {interaction_mode}")
            return

        if workflow_coroutine:
            self.task_manager.start_ai_workflow_task(workflow_coroutine)

    async def _get_description_from_image(self, image_bytes: bytes, media_type: str) -> str:
        """Asks a chat model to describe an image and returns the description."""
        self.log("info", "Image provided without text. Asking AI to describe the image for context...")
        if not self.service_manager: return ""

        llm_client = self.service_manager.get_llm_client()
        provider, model = llm_client.get_model_for_role("chat")

        if not provider or not model:
            self.log("error", "No 'chat' model configured for image description.")
            return ""

        description_prompt = "Describe the user interface, error message, or diagram shown in this image in detail. This description will be used as the prompt to generate or modify a software project."

        description = ""
        try:
            stream = llm_client.stream_chat(provider, model, description_prompt, "chat", image_bytes, media_type)
            async for chunk in stream:
                description += chunk
            self.log("success", f"AI generated description from image: {description[:100]}...")
            return description
        except Exception as e:
            self.log("error", f"Failed to get description from image: {e}")
            return ""

    def _on_session_cleared(self):
        self._last_generated_code = None
        self._is_plugin_override_active = False

    def handle_review_and_fix_request(self, error_report: str):
        # This method is retained for plugin compatibility but its core logic is disabled.
        if error_report:
            self.log("warning", "Review and fix from plugin was requested, but internal execution is disabled.")
        else:
            self.log("warning", "Received an empty error report to fix.")

    def log(self, level, message):
        self.event_bus.emit("log_message_received", "WorkflowManager", level, message)