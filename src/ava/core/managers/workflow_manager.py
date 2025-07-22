# src/ava/core/managers/workflow_manager.py
"""
This module defines the WorkflowManager, which orchestrates the core AI workflows.

The manager routes user requests to the appropriate workflow based on the current
interaction mode. It implements the primary 'Aura' chat workflow and the
sequential 'Plan -> Code -> Review -> Finish' build workflow.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional, Dict, TYPE_CHECKING, Any

from src.ava.core.app_state import AppState
from src.ava.core.event_bus import EventBus
from src.ava.core.interaction_mode import InteractionMode
from src.ava.prompts import AURA_REFINEMENT_PROMPT, CREATIVE_ASSISTANT_PROMPT
from src.ava.prompts.coder import CODER_PROMPT
from src.ava.prompts.finisher import FINISHER_PROMPT
from src.ava.prompts.reviewer import REVIEWER_PROMPT

if TYPE_CHECKING:
    from src.ava.core.managers.service_manager import ServiceManager
    from src.ava.core.managers.task_manager import TaskManager
    from src.ava.core.managers.window_manager import WindowManager

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Orchestrates AI workflows based on the authoritative application state.

    This class reads state from AppStateService but does not set it. It is the
    central hub for processing user requests, deciding whether to engage in a
    chat-like interaction (Aura) or a full-scale code generation process (Build).
    """

    def __init__(self, event_bus: EventBus):
        """
        Initializes the WorkflowManager.

        Args:
            event_bus: The application's central event bus for communication.
        """
        self.event_bus = event_bus
        self.service_manager: "ServiceManager" = None
        self.window_manager: "WindowManager" = None
        self.task_manager: "TaskManager" = None
        self._last_generated_code: Optional[Dict[str, str]] = None
        self._is_plugin_override_active = False
        logger.info("WorkflowManager Initialized")

    def set_managers(self, service_manager: "ServiceManager", window_manager: "WindowManager",
                     task_manager: "TaskManager"):
        """
        Set references to other managers and subscribe to relevant events.

        Args:
            service_manager: The manager for all application services.
            window_manager: The manager for UI windows.
            task_manager: The manager for background tasks.
        """
        self.service_manager = service_manager
        self.window_manager = window_manager
        self.task_manager = task_manager
        self.event_bus.subscribe("review_and_fix_from_plugin_requested", self.handle_review_and_fix_request)
        self.event_bus.subscribe("session_cleared", self._on_session_cleared)
        self.event_bus.subscribe("workflow_finalized", self._on_workflow_finalized)
        self.event_bus.subscribe("plugin_build_override_activated", self._activate_plugin_override)

    def _activate_plugin_override(self):
        """Called by a plugin to signal it's taking over the build process."""
        self._is_plugin_override_active = True

    def _on_workflow_finalized(self, final_code: Dict[str, str]):
        """
        Catches the final code after a build to be used by Aura.

        Args:
            final_code: A dictionary mapping filenames to their final content.
        """
        self.log("info", f"WorkflowManager captured {len(final_code)} final files for Aura's context.")
        self._last_generated_code = final_code
        self._is_plugin_override_active = False  # Reset override after a build completes

    async def _run_aura_workflow(self, user_idea: str, conversation_history: list, image_bytes: Optional[bytes],
                                 image_media_type: Optional[str]):
        """
        Runs the Aura persona workflow for chat-based interaction.

        Args:
            user_idea: The user's latest message.
            conversation_history: The history of the conversation.
            image_bytes: Optional bytes of an image provided by the user.
            image_media_type: The media type of the image (e.g., 'image/png').
        """
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

    async def _call_llm_agent(self, prompt: str, role: str, response_format: str = "text") -> Any:
        """
        Calls the LLM with a given prompt and role, handling streaming and parsing.

        Args:
            prompt: The complete prompt to send to the LLM.
            role: The agent role (e.g., 'coder', 'reviewer', 'finisher').
            response_format: The expected format of the response ('text' or 'json').

        Returns:
            The processed response, either as a string for 'text' or a dictionary for 'json'.

        Raises:
            ValueError: If no model is configured for the role or if JSON parsing fails.
            Exception: Propagates exceptions from the LLM client.
        """
        llm_client = self.service_manager.get_llm_client()
        provider, model = llm_client.get_model_for_role(role)
        if not provider or not model:
            self.log("error", f"No model configured for role '{role}'")
            raise ValueError(f"No model configured for role '{role}'")

        raw_response = ""
        try:
            stream = llm_client.stream_chat(provider, model, prompt, role)
            async for chunk in stream:
                raw_response += chunk
        except Exception as e:
            self.log("error", f"Error streaming from LLM for role '{role}': {e}", exc_info=True)
            raise

        if response_format == "json":
            try:
                match = re.search(r"\{.*\}", raw_response, re.DOTALL)
                if not match:
                    raise json.JSONDecodeError("No JSON object found in LLM response.", raw_response, 0)
                return json.loads(match.group(0))
            except json.JSONDecodeError as e:
                self.log("error", f"Failed to parse JSON from LLM for role '{role}': {e}")
                self.log("debug", f"Raw response that failed parsing: {raw_response}")
                raise ValueError(f"Invalid JSON response from {role} agent.") from e
        else:
            # Strip markdown code block fences if present
            if raw_response.strip().startswith("```") and raw_response.strip().endswith("```"):
                lines = raw_response.strip().split('\n')
                if len(lines) > 1:
                    return '\n'.join(lines[1:-1])
            return raw_response

    async def _run_build_workflow(self, prompt: str, existing_files: Optional[Dict[str, str]]):
        """
        Orchestrates the 'Plan -> Code -> Review -> Finish' assembly line.

        This workflow generates a plan, then executes each task in the plan through
        a sequence of specialized AI agents (Coder, Reviewer, Finisher) to
        produce high-quality code.

        Args:
            prompt: The user's request for what to build or modify.
            existing_files: A dictionary of existing project files and their content.
        """
        # 1. Get Services
        architect_service = self.service_manager.get_architect_service()
        project_manager = self.service_manager.get_project_manager()
        rag_manager = self.service_manager.get_rag_manager()
        project_indexer = self.service_manager.get_project_indexer_service()
        app_state_service = self.service_manager.get_app_state_service()

        # 2. Planning Phase
        self.log("info", "Build workflow started. Generating plan...")
        self.event_bus.emit("status_update", "Phase 1/5: Planning...")
        try:
            code_context_str = json.dumps(existing_files or {}, indent=2)
            rag_context = await rag_manager.query(prompt) or "No relevant context found."
            system_directive = "You are in MODIFY mode. The user wants to change the existing codebase." if existing_files else "You are in BOOTSTRAP mode. The user wants to create a new project from scratch."

            plan_json = await architect_service.generate_plan(
                user_request=prompt,
                code_context=code_context_str,
                rag_context=rag_context,
                system_directive=system_directive
            )
            if not plan_json or not isinstance(plan_json.get("tasks"), list):
                self.log("error", "Build workflow failed: Could not create a valid plan.")
                self.event_bus.emit("ai_response_ready", "Sorry, I couldn't create a plan for that request.")
                return
        except Exception as e:
            self.log("error", f"Build workflow failed during planning phase: {e}", exc_info=True)
            self.event_bus.emit("ai_response_ready", f"An error occurred during planning: {e}")
            return

        tasks = plan_json["tasks"]
        self.log("info", f"Plan generated with {len(tasks)} tasks.")
        self.event_bus.emit("status_update", f"Plan ready. Executing {len(tasks)} tasks...")

        # 3. Execution Phase (Assembly Line)
        generated_code_this_session: Dict[str, str] = {}
        final_code_to_write = (existing_files or {}).copy()
        symbol_index_json = json.dumps(project_indexer.get_symbol_index(), indent=2)

        for i, task in enumerate(tasks):
            task_name = f"{task.get('type', 'unknown')} {task.get('filename', '')}"
            self.log("info", f"Starting task {i+1}/{len(tasks)}: {task_name}")
            self.event_bus.emit("status_update", f"Task {i+1}/{len(tasks)}: {task_name}")

            try:
                task_type = task.get("type")
                filename = task.get("filename")

                if task_type == "create_file_with_content":
                    content = task.get("content", "")
                    final_code_to_write[filename] = content
                    generated_code_this_session[filename] = content
                    self.log("info", f"Task {i+1}: Created non-code file {filename}")
                    continue

                if task_type == "delete_file":
                    final_code_to_write[filename] = None  # Sentinel for deletion
                    if filename in generated_code_this_session:
                        del generated_code_this_session[filename]
                    self.log("info", f"Task {i+1}: Marked file for deletion: {filename}")
                    continue

                if task_type in ["create_file", "modify_file"]:
                    description = task["description"]
                    code_context_json = json.dumps(generated_code_this_session, indent=2)
                    original_code = ""
                    if task_type == "modify_file" and filename:
                        original_code = generated_code_this_session.get(filename) or (existing_files or {}).get(filename, "")

                    # STAGE 1: CODE
                    self.event_bus.emit("status_update", f"Task {i+1} ({filename}): 2/5 Coding...")
                    coder_prompt = CODER_PROMPT.format(
                        filename=filename,
                        description=description,
                        original_code_section=f"**ORIGINAL CODE for `{filename}`:**\n```python\n{original_code}\n```" if original_code else "",
                        code_context_json=code_context_json,
                        symbol_index_json=symbol_index_json
                    )
                    initial_code = await self._call_llm_agent(coder_prompt, "coder", "text")

                    # STAGE 2: REVIEW
                    self.event_bus.emit("status_update", f"Task {i+1} ({filename}): 3/5 Reviewing...")
                    reviewer_prompt = REVIEWER_PROMPT.format(
                        filename=filename,
                        description=description,
                        code_to_review=initial_code,
                        code_context_json=code_context_json,
                        symbol_index_json=symbol_index_json
                    )
                    review_result = await self._call_llm_agent(reviewer_prompt, "reviewer", "json")
                    self.log("info", f"Reviewer verdict for {filename}: is_correct={review_result.get('is_correct')}. Reason: {review_result.get('reasoning')}")
                    reviewed_code = review_result.get("fixed_code") if not review_result.get("is_correct") else initial_code

                    # STAGE 3: FINISH
                    self.event_bus.emit("status_update", f"Task {i+1} ({filename}): 4/5 Finishing...")
                    finisher_prompt = FINISHER_PROMPT.format(filename=filename, code_to_polish=reviewed_code)
                    finished_code = await self._call_llm_agent(finisher_prompt, "finisher", "text")

                    # Update state for the next task in the loop
                    final_code_to_write[filename] = finished_code
                    generated_code_this_session[filename] = finished_code
                    self.log("success", f"Task {i+1} ({filename}) completed successfully.")

            except Exception as e:
                self.log("error", f"Build workflow failed on task {i+1} ({task_name}): {e}", exc_info=True)
                self.event_bus.emit("ai_response_ready", f"Sorry, the build failed on task '{task_name}': {e}")
                self.event_bus.emit("status_update", f"Build failed on task: {task_name}")
                return

        # 4. Finalization Phase
        self.log("info", "All tasks completed. Finalizing build...")
        self.event_bus.emit("status_update", "Phase 5/5: Finalizing...")
        if project_manager and project_manager.git_manager:
            project_manager.git_manager.write_and_stage_files(final_code_to_write)
            commit_message = f"AI generation based on prompt: {prompt[:80]}"
            project_manager.git_manager.commit_staged_files(commit_message)
            self.log("info", "Build complete. Files written and committed.")

        self.event_bus.emit("workflow_finalized", final_code_to_write)
        self.event_bus.emit("status_update", "Build complete!")

    def handle_user_request(self, prompt: str, conversation_history: list,
                            image_bytes: Optional[bytes] = None, image_media_type: Optional[str] = None,
                            code_context: Optional[Dict[str, str]] = None):
        """
        The central router for all user chat input.

        This method determines the appropriate workflow (Aura or Build) based on
        the application's current interaction mode and state.

        Args:
            prompt: The user's text input.
            conversation_history: The list of previous messages in the chat.
            image_bytes: Optional image data.
            image_media_type: The media type of the image.
            code_context: Optional code context provided, e.g., from selected files.
        """
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
        """
        Asks a chat model to describe an image and returns the description.

        Args:
            image_bytes: The bytes of the image to describe.
            media_type: The media type of the image.

        Returns:
            A string description of the image generated by an AI model.
        """
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
        """Callback to reset the internal state of the workflow manager."""
        self.log("info", "Session cleared. Resetting internal workflow state.")
        self._last_generated_code = None
        self._is_plugin_override_active = False

    def handle_review_and_fix_request(self, error_report: str):
        """
        Handles a request to review and fix code based on an error report.

        Note: This is a placeholder for future functionality.

        Args:
            error_report: A string containing the error to be fixed.
        """
        if error_report:
            self.log("warning", "Review and fix from plugin was requested, but internal execution is disabled.")
        else:
            self.log("warning", "Received an empty error report to fix.")

    def log(self, level: str, message: str, **kwargs):
        """
        Emits a log message through the event bus.

        Args:
            level: The log level (e.g., 'info', 'error', 'debug').
            message: The log message.
            **kwargs: Additional keyword arguments for the logger.
        """
        self.event_bus.emit("log_message_received", "WorkflowManager", level, message, **kwargs)