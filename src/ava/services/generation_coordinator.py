```python
# src/ava/services/generation_coordinator.py
import asyncio
import io
import json
import logging
import re
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
from src.ava.prompts import REVIEWER_PROMPT
from src.ava.prompts.planner import CODE_SNIPPET_GENERATOR_PROMPT

logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """
    Manages the dynamic, multi-step 'Whiteboard' workflow for code generation
    and orchestrates the final 'Review and Correct' pass.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus, context_manager: Any,
                 import_fixer_service: Any, integration_validator: Any):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.context_manager = context_manager
        self.import_fixer_service = import_fixer_service
        self.integration_validator = integration_validator
        self.llm_client = service_manager.get_llm_client()

    async def coordinate_generation(self, whiteboard_plan: Dict[str, Any],
                                    existing_files: Optional[Dict[str, str]]) -> Dict[str, str]:
        try:
            self.log("info", "🚀 Starting Whiteboard generation workflow...")
            generated_files_this_session = (existing_files or {}).copy()
            tasks = whiteboard_plan.get("tasks", [])
            total_tasks = len(tasks)

            for i, task in enumerate(tasks):
                self.log("info", f"Executing task {i + 1}/{total_tasks}: {task.get('description')}")
                generated_files_this_session = await self._execute_task(task, generated_files_this_session)
                self.event_bus.emit("coordinated_generation_progress",
                                    {"filename": task.get('filename', 'Plan'), "completed": i + 1,
                                     "total": total_tasks})

            self.log("info", "Running post-generation import fixing pass...")
            self.event_bus.emit("agent_status_changed", "Fixer", "Fixing imports...", "fa5s.wrench")
            fixed_files = {}
            project_indexer = self.service_manager.get_project_indexer_service()
            project_manager = self.service_manager.get_project_manager()
            project_index = project_indexer.build_index(
                project_manager.active_project_path) if project_manager.active_project_path else {}

            for filename, content in generated_files_this_session.items():
                if filename.endswith('.py'):
                    module_path = filename.replace('.py', '').replace('/', '.')
                    fixed_content = self.import_fixer_service.fix_imports(content, project_index, module_path)
                    fixed_files[filename] = fixed_content
                else:
                    fixed_files[filename] = content
            generated_files_this_session = fixed_files
            self.log("success", "✅ Import fixing pass complete.")

            self.log("info", "🔬 Starting final 'Review and Correct' pass...")
            final_files = await self._perform_review_and_correct(generated_files_this_session)

            self.log("success", f"✅ Whiteboard generation complete. {len(final_files)} files processed.")
            return final_files

        except Exception as e:
            self.log("error", f"Coordinated generation failed: {e}")
            logger.exception("Exception in coordinate_generation")
            return {}

    async def _execute_task(self, task: Dict[str, Any], current_files: Dict[str, str]) -> Dict[str, str]:
        filename = task.get("filename")
        if not filename:
            self.log("warning", f"Task '{task.get('description')}' has no filename. Skipping.")
            return current_files

        # Emit event for every file generation task
        self.event_bus.emit("file_generation_starting", filename)
        await asyncio.sleep(0.1)  # Brief pause for UI responsiveness

        original_content = current_files.get(filename, "")

        self.event_bus.emit("agent_status_changed", "Coder", f"Implementing: {task.get('description')}", "fa5s.code")
        snippet = await self._generate_code_snippet(task, current_files)
        if snippet is None:
            snippet = f"\n# ERROR: Failed to generate code for task: {task.get('description')}\n"

        if task.get("type") != "create_file" and snippet and not snippet.endswith('\n'):
            snippet += '\n'

        if task.get("type") == "create_file":
            new_content = snippet
            await self._stream_content(filename, new_content, clear_first=True)
        else:
            lines = original_content.splitlines(True)
            if original_content.endswith('\n') and (not lines or not lines[-1].endswith('\n')):
                lines.append('\n')

            start_line = task.get("start_line", 1)
            end_line = task.get("end_line", start_line)
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)

            self.event_bus.emit("highlight_lines_for_edit", filename, start_line, end_line)
            await asyncio.sleep(0.5)
            self.event_bus.emit("delete_highlighted_lines", filename)
            await asyncio.sleep(0.3)
            self.event_bus.emit("position_cursor_for_insert", filename, start_line, 0)
            await asyncio.sleep(0.1)

            await self._stream_content(filename, snippet)

            new_lines = lines[:start_idx] + snippet.splitlines(True) + lines[end_idx:]
            new_content = "".join(new_lines)

        current_files[filename] = new_content
        return current_files

    async def _generate_code_snippet(self, task: Dict[str, Any], current_files: Dict[str, str]) -> Optional[str]:
        prompt = self._build_snippet_generation_prompt(task, current_files)
        provider, model = self.llm_client.get_model_for_role("coder")
        if not provider or not model:
            self.log("error", f"No model for 'coder' role. Cannot generate snippet for {task.get('filename')}.")
            return None

        snippet = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "coder"):
                snippet += chunk
            return self.robust_clean_llm_output(snippet)
        except Exception as e:
            self.log("error", f"LLM snippet generation failed for {task.get('filename')}: {e}")
            logger.exception("Exception in _generate_code_snippet")
            return None

    def _build_snippet_generation_prompt(self, task: Dict[str, Any], current_files: Dict[str, str]) -> str:
        filename = task.get("filename")
        file_content = current_files.get(filename, "# This is a new file.")
        other_files_context = {k: v for k, v in current_files.items() if k != filename}
        return CODE_SNIPPET_GENERATOR_PROMPT.format(
            task_json=json.dumps(task, indent=2),
            filename=filename,
            file_content=file_content,
            code_context_json=json.dumps(other_files_context, indent=2)
        )

    async def _perform_review_and_correct(self, generated_files: Dict[str, str]) -> Dict[str, str]:
        self.event_bus.emit("agent_status_changed", "Reviewer", "Analyzing generated code...", "fa5s.search")
        prompt = REVIEWER_PROMPT.format(code_to_review_json=json.dumps(generated_files, indent=2))
        provider, model = self.llm_client.get_model_for_role("reviewer")
        if not provider or not model:
            self.log("error", "No model for 'reviewer' role. Skipping review pass.")
            return generated_files

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "reviewer"):
                raw_response += chunk

            review_result = self.robust_parse_json_response(raw_response)
            if not review_result or not review_result.get("issues"):
                self.log("success", "✅ Review complete.