# src/ava/services/code_structure_service.py
import ast
from typing import Dict, Any


class CodeStructureService:
    """
    Uses Python's Abstract Syntax Tree (AST) module to parse the structure of
    Python source code. This is a fast and 100% reliable alternative to using
    an LLM for code analysis.
    """

    def parse_structure(self, code: str) -> Dict[str, Any]:
        """
        Parses Python code and returns a dictionary of its classes and functions.

        Args:
            code: The Python source code as a string.

        Returns:
            A dictionary detailing the classes (with methods) and standalone functions.
        """
        structure = {"classes": {}, "functions": {}}
        try:
            tree = ast.parse(code)
            for node in tree.body:
                # Handle standalone functions
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    func_code = ast.get_source_segment(code, node)
                    if func_code:
                        structure["functions"][func_name] = func_code

                # Handle classes and their methods
                elif isinstance(node, ast.ClassDef):
                    class_name = node.name
                    class_code = ast.get_source_segment(code, node)
                    class_info = {"methods": {}, "code": class_code or ""}
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_name = item.name
                            method_code = ast.get_source_segment(code, item)
                            if method_code:
                                class_info["methods"][method_name] = method_code
                    structure["classes"][class_name] = class_info
        except SyntaxError as e:
            # --- THIS IS THE FIX ---
            # Instead of failing silently, print the error so we know which file is broken.
            print(f"[CodeStructureService] ERROR: Failed to parse a file due to SyntaxError: {e}")
            # --- END OF FIX ---
            return {"classes": {}, "functions": {}}
        return structure