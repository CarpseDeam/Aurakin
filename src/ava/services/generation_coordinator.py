# src/ava/services/generation_coordinator.py
import asyncio
import json
import logging
import re
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
from src.ava.prompts.coder import MASTER_CODER_PROMPT

logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """
    Orchestrates the 'Architect (Plan) -> Coder -> Architect (Review)' workflow.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = service_manager.get_llm_client()
        self.project_indexer = service_manager.get_project_indexer_service()
        self.original_user_request = ""

    async def coordinate_generation(
            self,
            plan: Dict[str, Any],
            existing_files: Optional[Dict[str, str]],
            user_request: str,
    ) -> Optional[Dict[str, str]]:
        """
        Executes the lean 3-step generation pipeline.
        """
        self.original_user_request = user_request
        self.log("info", "🚀 Starting Lean Generation Assembly Line...")
        session_files = (existing_files or {}).copy()
        tasks = plan.get("tasks", [])

        # 1. Handle non-code files from the plan
        for task in tasks:
            if task.get("type") == "create_file_with_content":
                filename, content = task.get("filename"), task.get("content")
                if filename and content is not None:
                    session_files[filename] = content
                    await self._stream_content(filename, content)

        # 2. Coder Stage
        coded_files = await self._execute_coder_stage(tasks, session_files)
        if coded_files is None:
            return None

        # 3. Architect Review Stage
        reviewed_files = await self._execute_review_stage(coded_files)
        if reviewed_files is None:
            self.log("warning", "Review stage failed. Returning code from Coder stage.")
            return coded_files

        # 4. Handle file deletions
        final_files = reviewed_files.copy()
        for task in tasks:
            if task.get("type") == "delete_file" and (filename := task.get("filename")):
                final_files[filename] = None  # Sentinel for deletion

        self.log("success", "✅ Assembly Line Finished.")
        return final_files

    async def _execute_coder_stage(self, tasks: List[Dict], initial_files: Dict) -> Optional[Dict]:
        self.log("info", "--- Stage 1: Coder ---")
        session_files = initial_files.copy()

        project_root = self.service_manager.project_manager.active_project_path
        symbol_index = self.project_indexer.build_index(project_root) if project_root else {}
        symbol_index_json = json.dumps(symbol_index, indent=2)

        code_tasks = [t for t in tasks if t.get("type") in ["create_file", "modify_file"]]
        for i, task in enumerate(code_tasks):
            filename, description = task["filename"], task["description"]
            self.event_bus.emit("agent_status_changed", "Coder", f"({i + 1}/{len(code_tasks)}) Writing: {filename}",
                                "fa5s.code")
            self.event_bus.emit("file_generation_starting", filename)

            original_code_section = ""
            if task["type"] == "modify_file":
                original_code = session_files.get(filename, "")
                original_code_section = f"**ORIGINAL CODE:**\n```python\n{original_code}\n```"

            prompt = MASTER_CODER_PROMPT.format(
                filename=filename, description=description, original_code_section=original_code_section,
                code_context_json=json.dumps(session_files, indent=2), symbol_index_json=symbol_index_json
            )
            code = await self._call_llm_agent(prompt, "coder")
            if code is None:
                self.log("error", f"Coder agent failed for {filename}. Aborting.")
                return None
            session_files[filename] = code
            await self._stream_content(filename, code, clear_first=True)

        return session_files

    async def _execute_review_stage(self, files_to_review: Dict) -> Optional[Dict]:
        self.log("info", "--- Stage 2: Architect (Review) ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Reviewing all files...", "fa5s.search")

        architect = self.service_manager.get_architect_service()
        fixes_plan = await architect.review_and_fix(self.original_user_request, json.dumps(files_to_review, indent=2))

        if fixes_plan is None:
            self.log("warning", "Reviewer agent failed to return valid JSON. Skipping review.")
            return files_to_review

        if fixes := fixes_plan.get("fixes"):
            self.log("info", f"Architect found {len(fixes)} issues. Applying fixes...")
            return await self._apply_surgical_edits(files_to_review, fixes, "Architect")

        self.log("success", "Architect found no issues in review.")
        return files_to_review

    async def _apply_surgical_edits(self, original_files: Dict, edits: List[Dict], agent_name: str) -> Dict:
        modified_files = original_files.copy()
        for edit in edits:
            filename = edit.get("filename")
            start = edit.get("start_line")
            end = edit.get("end_line")
            corrected_code = edit.get("corrected_code")

            if not all([filename, start, end, corrected_code is not None]):
                self.log("warning", f"Reviewer provided an incomplete fix and it was discarded: {edit}")
                continue

            if filename not in modified_files:
                self.log("warning", f"{agent_name} tried to edit non-existent file: {filename}")
                continue

            self.log("info", f"Applying animated fix to {filename} at lines {start}-{end}")

            # --- RESTORED ANIMATION LOGIC ---
            # 1. Highlight the lines to be replaced
            self.event_bus.emit("highlight_lines_for_edit", filename, start, end)
            await asyncio.sleep(0.75)  # Let the user see the highlight

            # 2. Delete the highlighted lines
            self.event_bus.emit("delete_highlighted_lines", filename)
            await asyncio.sleep(0.4)  # Let the user see the deletion

            # 3. Position cursor and stream in the new code
            # We need to re-read the file content *after* the deletion to position the cursor correctly
            current_content_lines = modified_files[filename].splitlines()
            # The line number where the insertion will start is the original start line
            # (adjusting for 0-based index)
            insertion_line = start - 1
            # Calculate the column - usually the indentation of that line
            indentation = len(current_content_lines[insertion_line]) - len(
                current_content_lines[insertion_line].lstrip())

            # Position the cursor
            self.event_bus.emit("position_cursor_for_insert", filename, start, indentation)
            await asyncio.sleep(0.1)

            # Stream the corrected code to the cursor position
            await self._stream_content(filename, corrected_code, clear_first=False)

            # Update the in-memory version of the file for the next agent
            lines = modified_files[filename].splitlines()
            lines[start - 1:end] = corrected_code.splitlines()
            modified_files[filename] = "\n".join(lines)

        return modified_files

    async def _call_llm_agent(self, prompt: str, role: str) -> Optional[str]:
        provider, model = self.llm_client.get_model_for_role(role)
        if not provider or not model:
            self.log("error", f"No model configured for role '{role}'")
            return None
        raw_response = ""
        try:
            stream = self.llm_client.stream_chat(provider, model, prompt, role)
            async for chunk in stream:
                raw_response += chunk

            match = re.search(r"```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```", raw_response, re.DOTALL)
            if match:
                return match.group(1).strip()
            else:
                self.log("warning",
                         f"LLM for role '{role}' did not return code in a markdown block. Using raw response.")
                return raw_response.strip()

        except Exception as e:
            self.log("error", f"Error streaming from LLM for role '{role}': {e}", exc_info=True)
            return None

    async def _stream_content(self, filename: str, content: str, clear_first: bool = False):
        if clear_first:
            # An empty string signals the editor to clear its content
            self.event_bus.emit("stream_code_chunk", filename, "")
            await asyncio.sleep(0.05)  # Brief pause to ensure UI processes the clear

        # Stream the actual content
        for i in range(0, len(content), 50):
            chunk = content[i:i + 50]
            self.event_bus.emit("stream_code_chunk", filename, chunk)
            await asyncio.sleep(0.01)

    def log(self, level: str, message: str, **kwargs):
        self.event_bus.emit("log_message_received", "GenCoordinator", level, message, **kwargs)