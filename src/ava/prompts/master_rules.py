# src/ava/prompts/master_rules.py
import textwrap

# This rule is for any agent that must return a JSON object.
JSON_OUTPUT_RULE = """
**LAW: STRICT JSON OUTPUT**
- Your entire response MUST be a single, valid JSON object.
- Do not add any conversational text, explanations, or markdown before or after the JSON object.
- Your response must begin with `{{` and end with `}}`.
"""

# This rule is for the Coder agent.
LOGGING_RULE = """
**LAW: LOGGING OVER PRINTING**
- You are forbidden from using `print()` for debugging or status messages.
- You MUST use the `logging` module for all output.
- At the top of the file, you MUST write: `import logging` and `logger = logging.getLogger(__name__)`.
"""

# This rule is for any code-writing agent.
RAW_CODE_OUTPUT_RULE = """
**LAW: RAW CODE OUTPUT ONLY**
- Your entire response MUST be only the raw code for the assigned file.
- Do not write any explanations, comments, or markdown before or after the code.
"""

# This rule is for any file-writing agent to ensure data integrity.
NO_EMPTY_FILES_RULE = """
**LAW: GUARANTEE DATA INTEGRITY**
- The value for each file in your JSON response MUST be the FULL, corrected source code.
- Returning an empty or incomplete file is strictly forbidden and will be rejected.
"""

# NEW Rules for Perfect Python Practices
TYPE_HINTING_RULE = """
**LAW: MANDATORY TYPE HINTING**
- All function and method signatures MUST include type hints for all arguments and for the return value.
- Use the `typing` module where necessary (e.g., `List`, `Dict`, `Optional`).
- Example of a correct signature: `def my_function(name: str, count: int) -> bool:`
"""

DOCSTRING_RULE = """
**LAW: COMPREHENSIVE DOCSTRINGS**
- Every module, class, and public function MUST have a comprehensive docstring.
- Use Google-style docstrings.
- Module docstrings should describe the file's purpose.
- Function/method docstrings must describe the function's purpose, its arguments (`Args:`), and what it returns (`Returns:`).
"""

# NEW RULE FOR CODE QUALITY
SENIOR_DEV_PRINCIPLES_RULE = textwrap.dedent("""
    **LAW: SENIOR DEVELOPER PRINCIPLES.**
    - **Robustness:** Always include error handling (e.g., `try...except` blocks) for file operations, network requests, or potential `KeyError` exceptions.
    - **Clarity:** Use clear, descriptive variable and function names.
    - **Modularity:** Prefer smaller, single-purpose functions. If a function is doing more than one thing, it should be broken down.
    - **Qt Best Practices:** When writing PySide6 code, use the signal and slot mechanism for communication. Block signals when programmatically changing widget states to prevent infinite loops (e.g., `widget.blockSignals(True)`).
    """)