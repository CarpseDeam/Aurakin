# src/ava/services/implementation_service.py
import asyncio
import json
import ast
from typing import Dict, Any, Optional, List, Tuple

from src.ava.core.event_bus import EventBus
from src.ava.prompts import CODER_FILL_PROMPT
from src.ava.services.base_generation_service import BaseGenerationService


class ImplementationService(BaseGenerationService):
    """Phase 2: Coders fill in the scaffold's function bodies."""

    def __init__(self, service_manager: Any, event_bus: EventBus):
        super().__init__(service_manager, event_bus)

    async def execute(self, scaffold_files: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Executes the implementation phase, filling function bodies serially.

        Args:
            scaffold_files: The project skeleton with empty function bodies.

        Returns:
            The scaffold with function bodies filled, or None on failure.
        """
        self.log("info", "--- Phase 2: Coder agents deploying serially... ---")

        tasks_to_fill = self._find_functions_to_fill(scaffold_files)
        if not tasks_to_fill:
            self.log("warning", "No functions with 'pass' found to be filled in the scaffold.")
            return scaffold_files

        project_scaffold_json = json.dumps(scaffold_files, indent=2)
        implemented_code = scaffold_files.copy()

        for i, (filename, func_def) in enumerate(tasks_to_fill):
            self.log("info",
                     f"Coder starting task ({i + 1}/{len(tasks_to_fill)}): Implement {func_def['name']} in {filename}")
            self.event_bus.emit("agent_status_changed", "Coder",
                                f"({i + 1}/{len(tasks_to_fill)}) Implementing {func_def['name']}", "fa5s.code")

            prompt = CODER_FILL_PROMPT.format(
                project_scaffold=project_scaffold_json,
                filename=filename,
                function_signature=func_def['signature'],
                function_description=func_def['description']
            )
            function_body = await self._call_llm_agent(prompt, "coder")

            if function_body:
                # Animate the replacement in the UI with much shorter delays
                self.event_bus.emit("highlight_lines_for_edit", filename, func_def['pass_start_line'],
                                    func_def['pass_end_line'])
                await asyncio.sleep(0.1)
                self.event_bus.emit("delete_highlighted_lines", filename)
                await asyncio.sleep(0.1)

                # Replace the code in our local copy
                lines = implemented_code[filename].splitlines()
                pass_statement_line_index = func_def['pass_start_line'] - 1
                indentation = ' ' * func_def['col_offset']
                indented_body_lines = [f"{indentation}{line}" for line in function_body.splitlines()]

                # Replace the single 'pass' line with the new body
                lines[pass_statement_line_index:pass_statement_line_index + 1] = indented_body_lines
                implemented_code[filename] = "\n".join(lines)

                # Update the UI with the new content
                self.event_bus.emit("file_content_updated", filename, implemented_code[filename])
                await asyncio.sleep(0.05)
            else:
                self.log("warning",
                         f"Coder failed to provide a body for {func_def['name']} in {filename}. 'pass' will be kept.")

        return implemented_code

    def _find_functions_to_fill(self, scaffold_files: Dict[str, str]) -> List[Tuple[str, Dict[str, Any]]]:
        """Uses AST to find functions containing only docstrings and a single 'pass' statement."""
        fill_tasks = []
        for filename, content in scaffold_files.items():
            if not content.strip():
                continue
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        non_docstring_nodes = [
                            n for n in node.body
                            if not (isinstance(n, ast.Expr) and isinstance(n.value, (ast.Constant, ast.Str)))
                        ]

                        if len(non_docstring_nodes) == 1 and isinstance(non_docstring_nodes[0], ast.Pass):
                            pass_node = non_docstring_nodes[0]

                            # --- THE FIX: Use the docstring as the description ---
                            docstring = ast.get_docstring(node) or f"Implement the {node.name} function."

                            func_def = {
                                "name": node.name,
                                "signature": ast.get_source_segment(content, node).split(':\n')[0],
                                "description": docstring,
                                "pass_start_line": pass_node.lineno,
                                "pass_end_line": pass_node.end_lineno,
                                "col_offset": pass_node.col_offset
                            }
                            fill_tasks.append((filename, func_def))
            except Exception as e:
                self.log("error", f"Failed to parse scaffold file {filename} for implementation: {e}")
        return fill_tasks