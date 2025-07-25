# src/ava/services/code_extractor_service.py
import re
import inspect
from typing import Optional


class CodeExtractorService:
    """
    Surgically extracts the full source code of a single class or function from a file's content.
    This service is designed to be resilient to syntax errors in other parts of the file.
    """

    def extract_code_block(self, file_content: str, target_name: str) -> Optional[str]:
        """
        Extracts the full source code for a top-level function or class.

        Args:
            file_content: The full content of the source file.
            target_name: The name of the function or class to extract.

        Returns:
            The complete source code of the block, including decorators, or None if not found.
        """
        lines = file_content.splitlines()

        # Regex to find the start of a class or function definition
        # It captures decorators, async, and the definition line itself.
        start_pattern = re.compile(r"^\s*(?:@.*\s*)*?(?:async\s+)?(def|class)\s+" + re.escape(target_name) + r"\b")

        start_line_index = -1

        # Find the line where the function/class definition starts
        for i, line in enumerate(lines):
            if start_pattern.match(line):
                start_line_index = i
                break

        if start_line_index == -1:
            return None  # Target not found

        # Determine the base indentation of the function/class definition
        base_indent_str = re.match(r"^\s*", lines[start_line_index]).group(0)
        base_indent = len(base_indent_str)

        code_block_lines = []

        # Backtrack to capture any decorators
        decorator_index = start_line_index - 1
        while decorator_index >= 0 and lines[decorator_index].strip().startswith('@'):
            code_block_lines.insert(0, lines[decorator_index])
            decorator_index -= 1

        # Add the definition line itself
        code_block_lines.append(lines[start_line_index])

        # Capture the body of the function/class
        for i in range(start_line_index + 1, len(lines)):
            line = lines[i]
            if line.strip() == "":  # Preserve empty lines within the block
                code_block_lines.append(line)
                continue

            line_indent_str = re.match(r"^\s*", line).group(0)
            line_indent = len(line_indent_str)

            if line_indent > base_indent:
                code_block_lines.append(line)
            else:
                # We've reached the end of the indented block
                break

        # The extracted code might have extra indentation if it's defined inside another block (which this simple extractor doesn't handle).
        # We can use `inspect.cleandoc` to normalize the indentation of the captured block.
        return inspect.cleandoc("\n".join(code_block_lines))