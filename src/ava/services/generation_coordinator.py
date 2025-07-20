# src/ava/services/generation_coordinator.py
import asyncio
import io
import json
import logging
import re
from typing import Dict, Any, Optional, List

import unidiff
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
        """
        Initializes the GenerationCoordinator.

        Args:
            service_manager: The central service manager.
            event_bus: The application's event bus.
            context_manager: Manages the generation context.
            import_fixer_service: Service to fix missing imports.
            integration_validator: Validates code integration.
        """
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.context_manager = context_manager
        self.import_fixer_service = import_fixer_service
        self.integration_validator = integration_validator
        self.llm_client = service_manager.get_llm_client()

    async def coordinate_generation(self, whiteboard_plan: Dict[str, Any],
                                    existing_files: Optional[Dict[str, str]]) -> Dict[str, str]:
        """
        Coordinates the entire generation process based on the Whiteboard plan.

        Args:
            whiteboard_plan: The detailed, multi-step plan from the ArchitectService.
            existing_files: A dictionary of existing project files and their content.

        Returns:
            A dictionary of the final, generated/modified file contents.
        """
        try:
            self.log("info", "🚀 Starting Whiteboard generation workflow...")
            generated_files_this_session = (existing_files or {}).copy()
            tasks = whiteboard_plan.get("tasks", [])
            total_tasks = len(tasks)

            # --- 1. Execute all tasks from the Whiteboard plan ---
            for i, task in enumerate(tasks):
                self.log("info", f"Executing task {i + 1}/{total_tasks}: {task.get('description')}")
                generated_files_this_session = await self._execute_task(task, generated_files_this_session)
                self.event_bus.emit("coordinated_generation_progress",
                                    {"filename": task.get('filename', 'Plan'), "completed": i + 1, "total": total_tasks})

            # --- 2. Post-generation Import Fix Pass ---
            self.log("info", "Running post-generation import fixing pass...")
            self.event_bus.emit("agent_status_changed", "Fixer", "Fixing imports...", "fa5s.wrench")
            fixed_files = {}
            project_indexer = self.service_manager.get_project_indexer_service()
            project_manager = self.service_manager.get_project_manager()
            project_index = project_indexer.build_index(project_manager.active_project_path) if project_manager.active_project_path else {}

            for filename, content in generated_files_this_session.items():
                if filename.endswith('.py'):
                    module_path = filename.replace('.py', '').replace('/', '.')
                    fixed_content = self.import_fixer_service.fix_imports(content, project_index, module_path)
                    fixed_files[filename] = fixed_content
                else:
                    fixed_files[filename] = content
            generated_files_this_session = fixed_files
            self.log("success", "✅ Import fixing pass complete.")

            # --- 3. Final Review and Correct Pass ---
            self.log("info", "🔬 Starting final 'Review and Correct' pass...")
            final_files = await self._perform_review_and_correct(generated_files_this_session)

            self.log("success", f"✅ Whiteboard generation complete. {len(final_files)} files processed.")
            return final_files

        except Exception as e:
            self.log("error", f"Coordinated generation failed: {e}")
            logger.exception("Exception in coordinate_generation")
            return {}

    async def _execute_task(self, task: Dict[str, Any], current_files: Dict[str, str]) -> Dict[str, str]:
        """
        Executes a single task from the Whiteboard plan.

        Args:
            task: The task dictionary.
            current_files: The current state of all project files.

        Returns:
            The updated state of all project files after executing the task.
        """
        filename = task.get("filename")
        if not filename:
            self.log("warning", f"Task '{task.get('description')}' has no filename. Skipping.")
            return current_files

        original_content = current_files.get(filename, "")
        
        self.event_bus.emit("agent_status_changed", "Coder", f"Implementing: {task.get('description')}", "fa5s.code")
        snippet = await self._generate_code_snippet(task, current_files)
        if snippet is None:
            self.log("error", f"Failed to generate code snippet for task: {task.get('description')}")
            snippet = f"\n# ERROR: Failed to generate code for task: {task.get('description')}\n"

        if task.get("type") == "create_file":
            new_content = snippet
            await self._stream_content(filename, new_content, clear_first=True)
        else:
            lines = original_content.splitlines(True)
            start_line = task.get("start_line", 1)
            end_line = task.get("end_line", start_line)
            
            start_idx = max(0, start_line - 1)
            end_idx = max(0, end_line - 1)

            self.event_bus.emit("highlight_lines_for_edit", filename, start_line, end_line)
            await asyncio.sleep(0.5)
            self.event_bus.emit("delete_highlighted_lines", filename)
            await asyncio.sleep(0.3)
            self.event_bus.emit("position_cursor_for_insert", filename, start_line, 0)
            await asyncio.sleep(0.1)
            await self._stream_content(filename, snippet)

            new_lines = lines[:start_idx] + snippet.splitlines(True) + lines[end_idx + 1:]
            new_content = "".join(new_lines)

        current_files[filename] = new_content
        return current_files

    async def _generate_code_snippet(self, task: Dict[str, Any], current_files: Dict[str, str]) -> Optional[str]:
        """
        Generates a code snippet for a specific task using an LLM.

        Args:
            task: The task dictionary from the Whiteboard plan.
            current_files: The current state of all project files for context.

        Returns:
            The generated code snippet as a string, or None on failure.
        """
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
        """Builds the prompt for the code snippet generation agent."""
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
        """
        Orchestrates the final review pass, applying fixes if any are found.

        Args:
            generated_files: The complete set of files after the initial generation pass.

        Returns:
            The final, corrected set of files.
        """
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
                self.log("success", "✅ Review complete. No issues found.")
                return generated_files

            self.log("warning", f"Review found {len(review_result['issues'])} issues. Attempting to apply fixes...")
            self.event_bus.emit("agent_status_changed", "Surgeon", "Applying review fixes...", "fa5s.cut")
            
            corrected_files = generated_files.copy()
            for issue in review_result["issues"]:
                filename = issue.get("filename")
                patch_str = issue.get("unidiff_patch")
                if not filename or not patch_str or filename not in corrected_files:
                    self.log("warning", f"Skipping invalid issue from review: {issue}")
                    continue
                
                try:
                    cleaned_patch = self.robust_clean_llm_output(patch_str)
                    patch = unidiff.PatchSet(io.StringIO(cleaned_patch))
                    if not patch or len(patch) == 0:
                        raise ValueError("Could not parse the patch string from reviewer.")
                    
                    final_content = await self._animate_patch_in_ui(filename, corrected_files[filename], patch)
                    corrected_files[filename] = final_content
                    self.log("success", f"Applied fix to {filename}.")

                except Exception as e:
                    self.log("error", f"Failed to apply review fix to {filename}: {e}")
                    logger.exception(f"Patch application failed for {filename}")

            return corrected_files

        except Exception as e:
            self.log("error", f"Review and Correct pass failed: {e}")
            logger.exception("Exception in _perform_review_and_correct")
            return generated_files

    async def _animate_patch_in_ui(self, filename: str, original_content: str, patch: unidiff.PatchSet) -> str:
        """
        Applies a unidiff patch and animates the changes in the UI.

        Args:
            filename: The name of the file being patched.
            original_content: The original content of the file.
            patch: The parsed unidiff.PatchSet object.

        Returns:
            The new content of the file after applying the patch.
        """
        patched_lines = original_content.splitlines(True)
        offset = 0

        for hunk in patch[0]:
            start_line_idx = hunk.source_start - 1 + offset
            
            lines_to_add = [line.value for line in hunk if line.is_added]
            num_removed = hunk.source_length
            num_added = len(lines_to_add)

            if num_removed > 0:
                end_line_idx = start_line_idx + num_removed - 1
                self.event_bus.emit("highlight_lines_for_edit", filename, start_line_idx + 1, end_line_idx + 1)
                await asyncio.sleep(0.5)
                self.event_bus.emit("delete_highlighted_lines", filename)
                await asyncio.sleep(0.3)

            if num_added > 0:
                self.event_bus.emit("position_cursor_for_insert", filename, start_line_idx + 1, 0)
                await asyncio.sleep(0.1)
                await self._stream_content(filename, "".join(lines_to_add))

            patched_lines = patched_lines[:start_line_idx] + lines_to_add + patched_lines[start_line_idx + num_removed:]
            offset += (num_added - num_removed)

        return "".join(patched_lines)

    async def _stream_content(self, filename: str, content: str, clear_first: bool = False):
        """Streams content to the UI editor for a given file."""
        if clear_first:
            self.event_bus.emit("code_generation_complete", {filename: ""})
            await asyncio.sleep(0.1)

        chunk_size = 50
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            self.event_bus.emit("stream_code_chunk", filename, chunk)
            await asyncio.sleep(0.01)

    def robust_clean_llm_output(self, content: str) -> str:
        """Cleans LLM output, extracting code from markdown blocks if present."""
        content = content.strip()
        code_block_regex = re.compile(r'```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```', re.DOTALL)
        matches = code_block_regex.findall(content)
        if matches:
            return "\n".join(m.strip() for m in matches)
        return content

    def robust_parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Extracts a JSON object from a string, even if it's embedded in other text."""
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            self.log("error", "No JSON object found in reviewer response.", response)
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            self.log("error", f"Failed to decode JSON from reviewer. Error: {e}. Content: '{match.group(0)[:200]}...'")
            return None

    def log(self, level: str, message: str, details: str = ""):
        """Emits a log message through the application's event bus."""
        full_message = f"{message}\nDetails: {details}" if details else message
        self.event_bus.emit("log_message_received", "GenerationCoordinator", level, full_message)