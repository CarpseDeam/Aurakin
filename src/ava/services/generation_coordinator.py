# src/ava/services/generation_coordinator.py
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
from src.ava.prompts import (
    TASK_PLANNER_PROMPT,
    SCAFFOLDER_PROMPT,
    DEPENDENCY_ANALYZER_PROMPT,
    COMPLETER_PROMPT,
    REVIEWER_PROMPT,
    FINISHER_PROMPT,
)

# Use standard logging for services
logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """
    Orchestrates the 'Architect-Led Completion' multi-stage generation workflow.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus, **kwargs):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = service_manager.get_llm_client()
        self.project_manager = service_manager.get_project_manager()
        self.original_user_request = ""

    def _get_system_directive(self, existing_files: Optional[Dict[str, str]]) -> str:
        if not existing_files:
            return (
                "\n**SYSTEM DIRECTIVE:** This is a brand new project. Your output must ONLY include files and logic "
                "directly related to the user's request. You are strictly forbidden from including any concepts, code, "
                "or filenames from previous, unrelated projects. Confine your knowledge to the provided context."
            )
        return ""

    async def coordinate_architect_led_completion(
            self,
            whiteboard_plan: Dict[str, Any],
            existing_files: Optional[Dict[str, str]],
            user_request: str,
    ) -> Dict[str, str]:
        self.original_user_request = user_request
        self.log("info", "🚀 Starting Simplified Surgical Strike workflow...")
        system_directive = self._get_system_directive(existing_files)

        generated_files_this_session = (existing_files or {}).copy()
        code_tasks, content_tasks = self._classify_tasks(whiteboard_plan)

        generated_files_this_session = self._handle_content_tasks(
            content_tasks, generated_files_this_session
        )

        scaffolded_files, generated_files_this_session = await self._execute_scaffolding_stage(
            code_tasks, generated_files_this_session, whiteboard_plan, system_directive
        )
        if not scaffolded_files:
            self.log("error", "Scaffolding stage failed. Aborting workflow.")
            return generated_files_this_session

        dependency_order = await self._perform_dependency_analysis(
            scaffolded_files, whiteboard_plan, generated_files_this_session
        )

        completed_files = await self._execute_completion_stage(
            scaffolded_files, dependency_order, generated_files_this_session, system_directive
        )

        reviewed_files = await self._perform_final_review(completed_files)
        polished_files = await self._perform_final_polish(reviewed_files)

        self.log("success", f"✅ Workflow finished. {len(polished_files)} files processed.")
        return polished_files

    def _classify_tasks(
            self, plan: Dict[str, Any]
    ) -> tuple[List[Dict], List[Dict]]:
        code_tasks = []
        content_tasks = []
        for task in plan.get("tasks", []):
            if task.get("type") == "create_file_with_content":
                content_tasks.append(task)
            elif task.get("filename", "").endswith(".py"):
                code_tasks.append(task)
            else:
                content_tasks.append(task)
        return code_tasks, content_tasks

    def _handle_content_tasks(
            self, tasks: List[Dict], current_files: Dict[str, str]
    ) -> Dict[str, str]:
        for task in tasks:
            filename = task.get("filename")
            content = task.get("content")
            if filename and content is not None:
                current_files[filename] = content
                self.event_bus.emit("stream_code_chunk", filename, content)
        return current_files

    async def _execute_scaffolding_stage(
            self, tasks: List[Dict], current_files: Dict[str, str], plan: Dict[str, Any], system_directive: str
    ) -> tuple[Dict[str, str], Dict[str, str]]:
        scaffolds = {}
        for task in tasks:
            filename = task.get("filename")
            if not filename: continue
            self.event_bus.emit("agent_status_changed", "Architect", f"Scaffolding: {filename}", "fa5s.pencil-ruler")
            scaffold = await self._generate_scaffold_for_task(task, current_files, plan, system_directive)
            if scaffold:
                scaffolds[filename] = scaffold
                current_files[filename] = scaffold
                await self._stream_content(filename, scaffold, clear_first=True)
        return scaffolds, current_files

    async def _generate_scaffold_for_task(
            self, task: Dict, context_files: Dict, plan: Dict, system_directive: str
    ) -> Optional[str]:
        prompt = SCAFFOLDER_PROMPT.format(
            system_directive=system_directive,
            filename=task["filename"],
            task_json=json.dumps(task, indent=2),
            whiteboard_plan_json=json.dumps(plan, indent=2),
            code_context_json=json.dumps(context_files, indent=2),
        )
        provider, model = self.llm_client.get_model_for_role("architect")
        return await self._call_llm_for_code(provider, model, prompt, "architect")

    async def _perform_dependency_analysis(
            self, scaffolds: Dict, plan: Dict, project_files: Dict
    ) -> List[str]:
        # This function can remain as is, it's for ordering, not generation
        return list(scaffolds.keys())

    async def _execute_completion_stage(
            self, scaffolds: Dict, order: List, context_files: Dict, system_directive: str
    ) -> Dict[str, str]:
        completed_code = context_files.copy()
        for filename in order:
            if filename not in scaffolds: continue
            self.event_bus.emit("agent_status_changed", "Coder", f"Completing: {filename}", "fa5s.code")
            scaffold = scaffolds[filename]
            prompt = COMPLETER_PROMPT.format(
                system_directive=system_directive,
                scaffold_code=scaffold
            )
            provider, model = self.llm_client.get_model_for_role("coder")
            code = await self._call_llm_for_code(provider, model, prompt, "coder")
            if code:
                completed_code[filename] = code
                await self._stream_content(filename, code, clear_first=True)
        return completed_code

    async def _perform_final_review(self, files: Dict) -> Dict:
        # Simplified for now, just returns files
        self.log("info", "Skipping Final Review stage for simplicity.")
        return files

    async def _perform_final_polish(self, files: Dict) -> Dict:
        # Simplified for now, just returns files
        self.log("info", "Skipping Final Polish stage for simplicity.")
        return files

    async def _call_llm_for_code(
            self, provider: str, model: str, prompt: str, role: str
    ) -> Optional[str]:
        if not provider or not model: return None
        response_text = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, role):
                response_text += chunk
            return self.robust_clean_llm_output(response_text)
        except Exception:
            return None

    async def _stream_content(self, filename: str, content: str, clear_first: bool = False):
        if clear_first:
            self.event_bus.emit("stream_code_chunk", filename, "")
            await asyncio.sleep(0.05)
        chunk_size = 50
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            self.event_bus.emit("stream_code_chunk", filename, chunk)
            await asyncio.sleep(0.01)

    def robust_clean_llm_output(self, content: str) -> str:
        content = content.strip()
        code_block_regex = re.compile(r"```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```", re.DOTALL)
        matches = code_block_regex.findall(content)
        return "\n".join(m.strip() for m in matches) if matches else content

    def log(self, level: str, message: str):
        self.event_bus.emit("log_message_received", "GenCoordinator", level, message)