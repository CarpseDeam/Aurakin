# src/ava/services/generation_coordinator.py
import asyncio
import io
import json
import re
from typing import Dict, Any, Optional
import textwrap
from pathlib import Path

import unidiff
from src.ava.core.event_bus import EventBus
from src.ava.prompts import SURGICAL_CODER_PROMPT


class GenerationCoordinator:
    """
    Orchestrates code generation, routing between scaffold-and-fill for new files
    and surgical edits for existing files.
    """

    def __init__(self, service_manager, event_bus: EventBus, context_manager,
                 dependency_planner, integration_validator):
        """
        Initializes the GenerationCoordinator.

        Args:
            service_manager: The central service manager.
            event_bus: The application's event bus.
            context_manager: Manages the generation context.
            dependency_planner: Plans the file generation order.
            integration_validator: Validates code integration.
        """
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.context_manager = context_manager
        self.dependency_planner = dependency_planner
        self.integration_validator = integration_validator
        self.llm_client = service_manager.get_llm_client()

    async def coordinate_generation(self, plan: Dict[str, Any], rag_context: str,
                                    existing_files: Optional[Dict[str, str]]) -> Dict[str, str]:
        """
        Coordinates the entire generation process based on the provided plan.

        This method routes between two main workflows:
        1.  **Surgical Edit:** For modifying existing files, it generates and applies a unidiff patch.
        2.  **Scaffold-and-Fill:** For creating new files, it uses a two-step process of scaffolding
            followed by implementation filling.

        It determines the optimal order for file generation, updates the context after each
        file is generated to inform subsequent files, and streams all progress to the UI.

        Args:
            plan: The architectural plan from ArchitectService.
            rag_context: Contextual information retrieved from the RAG service.
            existing_files: A dictionary of existing file contents for modification tasks.

        Returns:
            A dictionary mapping filenames to their complete, generated/modified content.
        """
        try:
            self.log("info", "🚀 Starting coordinated generation...")
            context = await self.context_manager.build_generation_context(plan, rag_context, existing_files)
            generation_specs = await self.dependency_planner.plan_generation_order(context)
            generation_order = [spec.filename for spec in generation_specs]
            generated_files_this_session = {}
            total_files = len(generation_order)

            for i, filename in enumerate(generation_order):
                self.log("info", f"Processing file {i + 1}/{total_files}: {filename}")
                file_info = next((f for f in plan['files'] if f['filename'] == filename), None)
                if not file_info:
                    self.log("error", f"Could not find file info for {filename} in plan. Skipping.")
                    continue

                final_content = None

                # --- Workflow Router ---
                if 'surgical_instruction' in file_info:
                    # --- 1. Surgical Edit Workflow ---
                    self.log("info", f"Performing surgical edit on {filename}...")
                    self.event_bus.emit("agent_status_changed", "Surgeon", f"Modifying {filename}...", "fa5s.cut")

                    original_content = (existing_files or {}).get(filename)
                    if original_content is None:
                        self.log("error", f"Cannot perform surgical edit: original content for {filename} not found.")
                        final_content = f"# ERROR: Original content for {filename} not found for surgical edit."
                    else:
                        await self._stream_content(filename, original_content, clear_first=True)
                        await asyncio.sleep(1.5)  # Let user see original content

                        modified_content = await self._perform_surgical_edit(
                            file_info, context, generated_files_this_session, original_content
                        )
                        final_content = modified_content
                else:
                    # --- 2. Scaffold-and-Fill Workflow ---
                    self.log("info", f"Performing scaffold-and-fill for {filename}...")
                    scaffold_code = file_info.get("scaffold_code")
                    if not scaffold_code:
                        scaffold_code = f"# INFO: No scaffold code provided for {filename}. Generating from scratch."
                        self.log("warning", f"No scaffold_code found for {filename}. Generating from scratch.")

                    self.event_bus.emit("agent_status_changed", "Scaffolder", f"Displaying scaffold for {filename}...",
                                        "fa5s.drafting-compass")
                    await self._stream_content(filename, scaffold_code, clear_first=True)
                    await asyncio.sleep(1.5)

                    self.event_bus.emit("agent_status_changed", "Filler", f"Implementing {filename}...", "fa5s.fill-drip")
                    file_extension = Path(filename).suffix
                    if file_extension == '.py':
                        filled_content = await self._generate_filled_code(
                            file_info, context, generated_files_this_session
                        )
                    else:
                        self.log("info", f"Non-Python file '{filename}' detected. Using scaffold as final content.")
                        filled_content = scaffold_code
                    final_content = filled_content

                # --- Common Step: Process and Display Final Code ---
                if final_content is not None:
                    cleaned_content = self.robust_clean_llm_output(final_content)
                    await self._stream_content(filename, cleaned_content, clear_first=True)
                    generated_files_this_session[filename] = cleaned_content
                    context = await self.context_manager.update_session_context(context, {filename: cleaned_content})
                else:
                    self.log("error", f"Failed to generate content for {filename}.")
                    error_content = f"# ERROR: Failed to generate content for {filename}"
                    await self._stream_content(filename, error_content, clear_first=True)
                    generated_files_this_session[filename] = error_content

                self.event_bus.emit("coordinated_generation_progress",
                                    {"filename": filename, "completed": i + 1, "total": total_files})

            self.log("success",
                     f"✅ Coordinated generation complete: {len(generated_files_this_session)}/{total_files} files processed.")
            return generated_files_this_session

        except Exception as e:
            self.log("error", f"Coordinated generation failed: {e}")
            import traceback
            traceback.print_exc()
            return {}

    async def _stream_content(self, filename: str, content: str, clear_first: bool = False):
        """
        Streams content to the UI for a specific file, simulating typing.

        Args:
            filename: The name of the file to stream content to.
            content: The text content to be streamed.
            clear_first: If True, clears the editor for the file before streaming.
        """
        if clear_first:
            self.event_bus.emit("code_generation_complete", {filename: ""})
            await asyncio.sleep(0.1)

        chunk_size = 50
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            self.event_bus.emit("stream_code_chunk", filename, chunk)
            await asyncio.sleep(0.01)

    async def _generate_filled_code(self, file_info: Dict[str, Any], context: Any,
                                    generated_files_this_session: Dict[str, str]) -> Optional[str]:
        """
        Calls the 'filler' LLM to complete the implementation of a scaffolded file.

        Args:
            file_info: Dictionary containing file metadata, including the scaffold code.
            context: The current generation context.
            generated_files_this_session: Files already generated in this session.

        Returns:
            The complete, filled code as a string, or None on failure.
        """
        filename = file_info["filename"]
        prompt = self._build_filler_prompt(file_info, context, generated_files_this_session)

        provider, model = self.llm_client.get_model_for_role("filler")
        if not provider or not model:
            self.log("error", f"No model for 'filler' role. Cannot generate {filename}.")
            return None

        file_content = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "filler"):
                file_content += chunk
            return file_content
        except Exception as e:
            self.log("error", f"LLM generation failed for {filename}: {e}")
            return None

    def _build_filler_prompt(self, file_info: Dict[str, Any], context: Any,
                             generated_files_this_session: Dict[str, str]) -> str:
        """
        Constructs the prompt for the 'filler' model.

        Args:
            file_info: Dictionary containing file metadata.
            context: The current generation context.
            generated_files_this_session: Files already generated in this session.

        Returns:
            The formatted prompt string.
        """
        filename = file_info["filename"]
        scaffold_code = file_info.get("scaffold_code", "")
        purpose = file_info.get("purpose", "Complete the implementation based on the comments.")

        full_code_context = (context.existing_files or {}).copy()
        full_code_context.update(generated_files_this_session)
        if filename in full_code_context:
            del full_code_context[filename]

        FILLER_PROMPT = textwrap.dedent("""
            You are a junior developer AI. Your task is to complete a Python file based on a scaffold with detailed comments provided by a senior architect.

            **INSTRUCTIONS:**
            1.  Read the provided scaffold code and the comments within it.
            2.  Implement the logic described by the numbered comments (`# 1.`, `# 2.`, etc.).
            3.  Replace the `pass` statements with your implementation.
            4.  Your final output MUST be the complete, fully implemented Python code for the file.
            5.  Do not add any explanations, markdown, or commentary outside of the code. Just provide the raw code.
            6.  Ensure you respect all imports and function signatures from the scaffold.

            **CONTEXT FROM OTHER PROJECT FILES:**
            ```json
            {code_context_json}
            ```

            ---
            **FILE TO COMPLETE: `{filename}`**
            **PURPOSE:** {purpose}

            **SCAFFOLD CODE:**
            ```python
            {scaffold_code}
            ```
            ---

            Now, provide the complete and final code for `{filename}`.
        """)

        return FILLER_PROMPT.format(
            filename=filename,
            purpose=purpose,
            scaffold_code=scaffold_code,
            code_context_json=json.dumps(full_code_context, indent=2)
        )

    async def _perform_surgical_edit(self, file_info: Dict[str, Any], context: Any,
                                     generated_files_this_session: Dict[str, str],
                                     original_content: str) -> str:
        """
        Calls a 'surgeon' LLM to generate a unidiff patch and applies it to the original content.

        Args:
            file_info: Dictionary containing file metadata, including the surgical instruction.
            context: The current generation context.
            generated_files_this_session: Files already generated in this session.
            original_content: The original content of the file to be modified.

        Returns:
            The modified code as a string, or the original code with an error comment on failure.
        """
        filename = file_info["filename"]
        prompt = self._build_surgeon_prompt(file_info, context, generated_files_this_session, original_content)

        provider, model = self.llm_client.get_model_for_role("coder")
        if not provider or not model:
            self.log("error", f"No model for 'coder' role. Cannot perform surgical edit on {filename}.")
            return f"# SURGICAL EDIT FAILED: No 'coder' model configured.\n\n{original_content}"

        patch_str = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "coder"):
                patch_str += chunk

            if not patch_str.strip():
                self.log("error", f"LLM returned an empty patch for {filename}.")
                return f"# SURGICAL EDIT FAILED: LLM returned an empty patch.\n\n{original_content}"

            cleaned_patch = self.robust_clean_llm_output(patch_str)
            patched_content = self._apply_unidiff_patch(original_content, cleaned_patch)

            if patched_content is None:
                self.log("error", f"Failed to apply patch to {filename}. Patch might be invalid.")
                return f"# SURGICAL EDIT FAILED: Could not apply generated patch.\n\n{original_content}"

            return patched_content
        except Exception as e:
            self.log("error", f"Surgical edit failed for {filename}: {e}")
            return f"# SURGICAL EDIT FAILED: {e}\n\n{original_content}"

    def _build_surgeon_prompt(self, file_info: Dict[str, Any], context: Any,
                              generated_files_this_session: Dict[str, str],
                              original_content: str) -> str:
        """
        Constructs the prompt for the 'surgeon' model to generate a diff patch.

        Args:
            file_info: Dictionary containing file metadata.
            context: The current generation context.
            generated_files_this_session: Files already generated in this session.
            original_content: The original content of the file to be modified.

        Returns:
            The formatted prompt string.
        """
        filename = file_info["filename"]
        instruction = file_info["surgical_instruction"]

        full_code_context = (context.existing_files or {}).copy()
        full_code_context.update(generated_files_this_session)
        if filename in full_code_context:
            del full_code_context[filename]

        prompt_base = SURGICAL_CODER_PROMPT.format(
            filename=filename,
            surgical_instruction=instruction,
            symbol_index_json=json.dumps(context.project_index, indent=2),
            code_context_json=json.dumps(full_code_context, indent=2)
        )

        return f"{prompt_base}\n{original_content}"

    def _apply_unidiff_patch(self, original_content: str, patch_str: str) -> Optional[str]:
        """
        Applies a unidiff patch to the original content using the unidiff library.

        Args:
            original_content: The original string content of the file.
            patch_str: The unidiff patch as a string.

        Returns:
            The patched content as a string, or None if the patch cannot be applied.
        """
        try:
            patch = unidiff.PatchSet(io.StringIO(patch_str))
            if not patch or len(patch) == 0:
                self.log("error", "Could not parse the patch string into a valid PatchSet.")
                return None

            patched_file = patch[0]
            original_lines = original_content.splitlines(keepends=True)
            patched_content_lines = []
            original_line_idx = 0

            for hunk in patched_file:
                while original_line_idx < hunk.source_start - 1:
                    if original_line_idx < len(original_lines):
                        patched_content_lines.append(original_lines[original_line_idx])
                    original_line_idx += 1

                for line in hunk:
                    if line.is_context:
                        patched_content_lines.append(line.value)
                        original_line_idx += 1
                    elif line.is_added:
                        patched_content_lines.append(line.value)
                    elif line.is_removed:
                        original_line_idx += 1

            while original_line_idx < len(original_lines):
                patched_content_lines.append(original_lines[original_line_idx])
                original_line_idx += 1

            return "".join(patched_content_lines)
        except Exception as e:
            self.log("error", f"Failed to apply unidiff patch: {e}")
            return None

    def robust_clean_llm_output(self, content: str) -> str:
        """
        Cleans the output from an LLM, primarily by extracting code from markdown blocks.

        Args:
            content: The raw string output from the LLM.

        Returns:
            The cleaned, code-only string.
        """
        content = content.strip()
        code_block_regex = re.compile(r'```(?:[a-zA-Z0-9_]*)?\n(.*?)\n```', re.DOTALL)
        matches = code_block_regex.findall(content)

        if matches:
            return "\n".join(m.strip() for m in matches)
        else:
            return content

    def log(self, level: str, message: str):
        """
        Emits a log message through the application's event bus.

        Args:
            level: The log level (e.g., 'info', 'error').
            message: The log message content.
        """
        self.event_bus.emit("log_message_received", "GenerationCoordinator", level, message)