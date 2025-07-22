from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Any

from src.ava.core.event_bus import EventBus
from src.ava.core.llm_client import LLMClient
from src.ava.core.project_manager import ProjectManager
from src.ava.prompts.planner import TASK_PLANNER_PROMPT, LINE_LOCATOR_PROMPT
from src.ava.services.rag_service import RAGService
from src.ava.services.project_indexer_service import ProjectIndexerService

if TYPE_CHECKING:
    from src.ava.core.managers import ServiceManager

logger = logging.getLogger(__name__)


class ArchitectService:
    """
    A service that functions as a high-level planner for code generation.
    """

    def __init__(self, service_manager: 'ServiceManager', event_bus: EventBus,
                 llm_client: LLMClient, project_manager: ProjectManager,
                 rag_service: RAGService, project_indexer: ProjectIndexerService):
        """
        Initializes the ArchitectService.

        Args:
            service_manager: The main service manager.
            event_bus: The application's event bus.
            llm_client: The client for interacting with LLMs.
            project_manager: The manager for the active project.
            rag_service: The service for RAG queries.
            project_indexer: The service for indexing project symbols.
        """
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.project_manager = project_manager
        self.rag_service = rag_service
        self.project_indexer = project_indexer

    async def create_whiteboard_plan(self, user_request: str, existing_files: Optional[Dict[str, str]]) -> Optional[
        Dict[str, Any]]:
        """
        Creates a detailed, multi-step "Whiteboard" plan for code generation.

        Args:
            user_request: The user's request for code generation or modification.
            existing_files: A dictionary of existing files and their content.

        Returns:
            A dictionary representing the detailed plan, or None if planning fails.
        """
        self.log("info", f"Architect received request: '{user_request[:100]}...'")
        self.event_bus.emit("agent_status_changed", "Architect", "Planning tasks...", "fa5s.tasks")

        task_plan = await self._generate_task_plan(user_request, existing_files)
        if not task_plan or "tasks" not in task_plan:
            self.log("error", "Failed to generate a valid initial task plan.")
            return None

        # --- NEW: Emit event for real-time visualization ---
        self.event_bus.emit("project_plan_generated", task_plan)
        # --- END NEW ---

        self.log("success", f"Generated {len(task_plan['tasks'])} high-level tasks.")
        self.event_bus.emit("agent_status_changed", "Architect", "Locating code for changes...", "fa5s.search-location")

        augmented_tasks = []
        total_tasks = len(task_plan["tasks"])
        for i, task in enumerate(task_plan["tasks"]):
            self.log("info", f"({i + 1}/{total_tasks}) Processing task: {task.get('description')}")
            if task.get("type") in ["modify_code", "insert_code", "delete_code"]:
                if "filename" not in task:
                    augmented_tasks.append(task)
                    continue

                file_content = (existing_files or {}).get(task["filename"])
                if not file_content:
                    task['type'] = 'create_file'
                    augmented_tasks.append(task)
                    continue

                augmented_task = await self._locate_lines_for_task(task, file_content)
                augmented_tasks.append(augmented_task)
            else:
                augmented_tasks.append(task)

        task_plan["tasks"] = augmented_tasks
        self.log("success", "Whiteboard plan complete with line locations.")
        return task_plan

    async def _generate_task_plan(self, user_request: str, existing_files: Optional[Dict[str, str]]) -> Optional[
        Dict[str, Any]]:
        """
        Generates the high-level task plan using an LLM.

        Args:
            user_request: The user's request.
            existing_files: The content of existing project files.

        Returns:
            The parsed JSON plan from the LLM, or None on failure.
        """
        self.log("info", "Generating high-level task plan...")

        is_new_project = not existing_files
        system_directive = ""
        rag_context = ""

        if is_new_project:
            self.log("info", "New project detected. Applying strict context directive and skipping RAG.")
            system_directive = (
                "\n**SYSTEM DIRECTIVE:** This is a brand new project. Your plan must ONLY include files and logic "
                "directly related to the user's request. You are forbidden from including any concepts or code from "
                "previous, unrelated projects."
            )
        else:
            self.log("info", "Existing project detected. Querying RAG for context.")
            rag_context = await self._get_combined_rag_context(user_request)

        code_context_str = json.dumps(existing_files, indent=2) if existing_files else "{}"

        prompt = TASK_PLANNER_PROMPT.format(
            system_directive=system_directive,
            user_request=user_request,
            code_context=code_context_str,
            rag_context=rag_context
        )

        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            self.handle_error("architect", "No model configured for architect role.")
            return None

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "architect"):
                raw_response += chunk

            plan = self._parse_json_response(raw_response)
            if not plan or not isinstance(plan.get("tasks"), list):
                raise ValueError("AI did not return a valid task plan in JSON format.")

            return plan
        except Exception as e:
            self.handle_error("architect", f"Task plan creation failed: {e}", raw_response)
            return None

    async def _locate_lines_for_task(self, task: Dict[str, Any], file_content: str) -> Dict[str, Any]:
        """
        Uses an LLM to find the start and end lines for a modification task.

        Args:
            task: The task dictionary.
            file_content: The content of the file to be modified.

        Returns:
            The task dictionary, augmented with 'start_line' and 'end_line' if found.
        """
        filename = task["filename"]
        description = task["description"]
        self.log("info", f"Locating lines in '{filename}' for task: '{description}'")

        prompt = LINE_LOCATOR_PROMPT.format(
            filename=filename,
            task_description=description,
            file_content=file_content
        )

        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            return task

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "architect"):
                raw_response += chunk

            location_data = self._parse_json_response(raw_response)
            if isinstance(location_data.get("start_line"), int) and isinstance(location_data.get("end_line"), int):
                task["start_line"] = location_data["start_line"]
                task["end_line"] = location_data["end_line"]
            return task
        except Exception as e:
            self.handle_error("architect", f"Line location failed for {filename}: {e}", raw_response)
            return task

    async def _get_combined_rag_context(self, prompt: str) -> str:
        """
        Queries both project and global RAG collections and combines the results.

        Args:
            prompt: The user's query prompt.

        Returns:
            A formatted string containing context from both RAG collections.
        """
        project_rag_context = await self.rag_service.query(prompt, target_collection="project")
        global_rag_context = await self.rag_service.query(prompt, target_collection="global")
        context_parts = []
        if "no relevant documents found" not in project_rag_context.lower():
            context_parts.append(f"PROJECT-SPECIFIC CONTEXT:\n{project_rag_context}")
        if "no relevant documents found" not in global_rag_context.lower():
            context_parts.append(f"GENERAL CONTEXT:\n{global_rag_context}")
        return "\n\n---\n\n".join(context_parts) if context_parts else "No specific RAG context found."

    def _parse_json_response(self, response: str) -> dict:
        """
        Robustly parses a JSON object from a string that may contain other text.

        Args:
            response: The string containing the JSON object.

        Returns:
            The parsed dictionary.

        Raises:
            ValueError: If no JSON object is found in the response.
        """
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in the response.")
        return json.loads(match.group(0))

    def handle_error(self, agent: str, error_msg: str, response: str = ""):
        """
        Logs an error and emits an event to notify the user.

        Args:
            agent: The name of the agent that failed.
            error_msg: The error message.
            response: The raw response from the LLM, if any.
        """
        self.log("error", f"{agent} failed: {error_msg}\nResponse: {response}")
        self.event_bus.emit("ai_response_ready", f"Sorry, the {agent} failed.")

    def log(self, level: str, message: str, details: str = ""):
        """
        Sends a log message through the event bus.

        Args:
            level: The log level (e.g., 'info', 'error').
            message: The main log message.
            details: Optional additional details.
        """
        full_message = f"{message}\nDetails: {details}" if details else message
        self.event_bus.emit("log_message_received", "ArchitectService", level, full_message)