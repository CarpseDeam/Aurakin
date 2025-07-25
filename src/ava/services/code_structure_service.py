# src/ava/services/code_structure_service.py
import re
from typing import Dict, Any


class CodeStructureService:
    """
    Uses a resilient regex-based approach to discover the names of classes and functions
    for visualization. This is not a full parser but is robust against syntax errors.
    """

    def parse_structure(self, code: str) -> Dict[str, Any]:
        """
        Scans Python code and returns a dictionary of its classes and functions.
        This method is designed to be resilient and will find names even if the
        file has syntax errors.

        Args:
            code: The Python source code as a string.

        Returns:
            A dictionary detailing the names of classes and standalone functions.
            The 'code' value is intentionally left blank as this is not a full parser.
        """
        structure = {"classes": {}, "functions": {}}

        # Regex to find top-level class and function definitions.
        # It captures the name of the class/function.
        # It's simplified to look for lines starting with 'class' or 'def'.
        pattern = re.compile(r"^(class|def)\s+([a-zA-Z_]\w*)")

        for line in code.splitlines():
            match = pattern.match(line.strip())
            if match:
                keyword, name = match.groups()
                if keyword == "class":
                    # For visualization, we only need the name. The code block
                    # will be extracted on-demand by the CodeExtractorService.
                    structure["classes"][name] = {"methods": {}, "code": ""}
                elif keyword == "def":
                    structure["functions"][name] = ""  # Just the name is needed.

        return structure