# src/ava/services/architect_service.py
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

if TYPE_CHECKING:
    from src.ava.core.managers import ServiceManager

logger = logging.getLogger(__name__)


class ArchitectService:
    """
    A service that functions as a high-level planner for code generation.

    It deconstructs a user's request into a structured "Whiteboard" plan,
    which includes a series of tasks. For tasks involving code modification,
    it also pinpoints the exact line numbers to be changed.
    """

    def __init__(self, service_manager: 'ServiceManager', event_bus: EventBus,
                 llm_client: LLMClient, project_manager: ProjectManager,
                 rag_service: RAGService):
        """
        Initializes the ArchitectService.

        Args:
            service_manager: The main service manager for dependency injection.
            event_bus: The application's event bus for communication.
            llm_client: The client for interacting with language models.
            project_manager: Manages the active project's state and files.
            rag_service: The service for retrieving context from knowledge bases.
        """
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.project_manager = project_manager
        self.rag_service = rag_service

    async def create_whiteboard_plan(self, user_request: str, existing_files: Optional[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """
        Creates a detailed, multi-step "Whiteboard" plan for code generation.

        This involves two main phases:
        1. Task Planning: Deconstructs the user request into a list of high-level tasks.
        2. Line Location: For each modification task, pinpoints the exact code lines to be changed.

        Args:
            user_request: The user's high-level request for code changes.
            existing_files: A dictionary of existing project files and their content.

        Returns:
            A dictionary representing the final, augmented plan, or None if planning fails.
        """
        self.log("info", f"Architect received request: '{user_request[:100]}...'")
        self.event_bus.emit("agent_status_changed", "Architect", "Planning tasks...", "fa5s.tasks")

        # 1. Generate the initial high-level task plan
        task_plan = await self._generate_task_plan(user_request, existing_files)
        if not task_plan or "tasks" not in task_plan:
            self.log("error", "Failed to generate a valid initial task plan.")
            return None

        self.log("success", f"Generated {len(task_plan['tasks'])} high-level tasks.")
        self.event_bus.emit("agent_status_changed", "Architect", "Locating code for changes...", "fa5s.search-location")

        # 2. Augment the plan by locating lines for each modification task
        augmented_tasks = []
        total_tasks = len(task_plan["tasks"])
        for i, task in enumerate(task_plan["tasks"]):
            self.log("info", f"({i + 1}/{total_tasks}) Processing task: {task.get('description')}")
            if task.get("type") in ["modify_code", "insert_code", "delete_code"]:
                if "filename" not in task:
                    self.log("warning", f"Skipping line location for task without filename: {task.get('description')}")
                    augmented_tasks.append(task)
                    continue

                file_content = (existing_files or {}).get(task["filename"])
                if not file_content:
                    self.log("warning", f"Cannot locate lines for '{task['filename']}' as it does not exist. Treating as new file task.")
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

    async def _generate_task_plan(self, user_request: str, existing_files: Optional[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """
        Calls the LLM with the TASK_PLANNER_PROMPT to get a high-level task list.

        Args:
            user_request: The user's natural language request.
            existing_files: The current state of files in the project.

        Returns:
            A dictionary containing the structured task plan, or None on failure.
        """
        self.log("info", "Generating high-level task plan...")
        rag_context = await self._get_combined_rag_context(user_request)
        code_context_str = json.dumps(existing_files, indent=2) if existing_files else "{}"

        prompt = TASK_PLANNER_PROMPT.format(
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
                self.log("error", "The AI's task plan was invalid or missing the 'tasks' list.", raw_response)
                raise ValueError("AI did not return a valid task plan in JSON format.")

            return plan
        except (json.JSONDecodeError, ValueError) as e:
            self.handle_error("architect", f"Task plan creation failed: {e}", raw_response)
            return None
        except Exception as e:
            self.handle_error("architect", f"An unexpected error during task planning: {e}", raw_response)
            return None

    async def _locate_lines_for_task(self, task: Dict[str, Any], file_content: str) -> Dict[str, Any]:
        """
        Calls the LLM with the LINE_LOCATOR_PROMPT to find the start and end lines for a task.

        Args:
            task: The task dictionary, containing a description and filename.
            file_content: The full content of the file to be analyzed.

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
            self.handle_error("architect", "No model configured for architect role.")
            return task

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "architect"):
                raw_response += chunk

            location_data = self._parse_json_response(raw_response)

            if isinstance(location_data.get("start_line"), int) and isinstance(location_data.get("end_line"), int):
                task["start_line"] = location_data["start_line"]
                task["end_line"] = location_data["end_line"]
                self.log("success", f"Located lines {task['start_line']}-{task['end_line']} for task.")
            else:
                self.log("warning", "Line locator did not return valid start/end lines.", raw_response)

            return task
        except (json.JSONDecodeError, ValueError) as e:
            self.handle_error("architect", f"Line location failed for {filename}: {e}", raw_response)
            return task
        except Exception as e:
            self.handle_error("architect", f"An unexpected error during line location for {filename}: {e}", raw_response)
            return task

    async def _get_combined_rag_context(self, prompt: str) -> str:
        """
        Queries both project and global RAG collections and combines the results.

        Args:
            prompt: The user query to search for.

        Returns:
            A formatted string containing context from both knowledge bases.
        """
        project_rag_context = await self.rag_service.query(prompt, target_collection="project")
        global_rag_context = await self.rag_service.query(prompt, target_collection="global")

        valid_project_context = project_rag_context if "no relevant documents found" not in project_rag_context.lower() and "not running or is unreachable" not in project_rag_context.lower() else ""
        valid_global_context = global_rag_context if "no relevant documents found" not in global_rag_context.lower() and "not running or is unreachable" not in global_rag_context.lower() else ""

        combined_context_parts = []
        if valid_project_context:
            combined_context_parts.append(
                f"PROJECT-SPECIFIC CONTEXT (e.g., GDD, existing project files):\n{valid_project_context}")
        if valid_global_context:
            combined_context_parts.append(
                f"GENERAL PYTHON EXAMPLES & BEST PRACTICES (GLOBAL CONTEXT):\n{valid_global_context}")

        if not combined_context_parts:
            return "No specific RAG context found for this query."

        return "\n\n---\n\n".join(combined_context_parts)

    def _parse_json_response(self, response: str) -> dict:
        """
        Extracts a JSON object from a string, even if it's embedded in other text.

        Args:
            response: The string response from the LLM.

        Returns:
            The parsed dictionary from the JSON object.

        Raises:
            ValueError: If no JSON object is found or if decoding fails.
        """
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            self.log("error", "No JSON object found in response.", response)
            raise ValueError("No JSON object found in the response.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            self.log("error", f"Failed to decode JSON. Error: {e}. Content: '{match.group(0)[:200]}...'", response)
            raise ValueError(f"Failed to decode JSON. Error: {e}.")

    def handle_error(self, agent: str, error_msg: str, response: str = ""):
        """
        Logs an error and emits an event to notify the user.

        Args:
            agent: The name of the agent or process that failed.
            error_msg: The error message.
            response: The raw LLM response, if available.
        """
        self.log("error", f"{agent} failed: {error_msg}\nResponse: {response}")
        self.event_bus.emit("ai_response_ready", f"Sorry, the {agent} failed.")

    def log(self, level: str, message: str, details: str = ""):
        """
        Emits a log message through the application's event bus.

        Args:
            level: The log level (e.g., 'info', 'error').
            message: The main log message.
            details: Optional additional details.
        """
        full_message = f"{message}\nDetails: {details}" if details else message
        self.event_bus.emit("log_message_received", "ArchitectService", level, full_message)