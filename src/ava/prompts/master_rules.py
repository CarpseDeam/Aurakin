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

# SUPERCHARGED RULE FOR CODE QUALITY ACROSS ALL DOMAINS
SENIOR_DEV_PRINCIPLES_RULE = textwrap.dedent("""
    **LAW: SENIOR DEVELOPER PRINCIPLES - YOU MUST ADHERE TO THESE AT ALL TIMES.**

    1.  **ROBUSTNESS & ERROR HANDLING:**
        -   **NEVER trust external inputs or resources.** Aggressively use `try...except` blocks for file operations (`FileNotFoundError`, `IOError`), network requests (`requests.exceptions.RequestException`), and dictionary key access (`KeyError`).
        -   **Configuration Management:** For API keys, database URLs, or other secrets, your code should read from environment variables using `os.getenv('MY_VARIABLE')`. Never hardcode secrets.
        -   **Graceful Failure:** Your code should anticipate potential failures and handle them gracefully, logging errors instead of crashing.

    2.  **MAINTAINABILITY & CLARITY:**
        -   **Single Responsibility Principle (SRP):** Every function and class should do ONE thing and do it well. If a function is named `get_user_and_update_avatar`, it should be split into two separate functions.
        -   **Descriptive Naming:** Use clear, unambiguous names for variables, functions, and classes. `user_profile` is better than `data`.
        -   **Modularity:** Group related functions into separate files (modules). Create services for business logic, models for data structures, and utils for common helpers.

    3.  **MODERN & EFFICIENT PYTHON:**
        -   **Always prefer `pathlib.Path` over `os.path`** for all file system operations. It is cleaner and object-oriented.
        -   **Use Dataclasses:** For simple data-holding objects, always prefer `@dataclass` for its conciseness and power.
        -   **Use F-strings:** All string formatting must use f-strings (e.g., `f"Hello, {{name}}"`).
        -   **Dependency Management:** All external libraries MUST be listed in a `requirements.txt` file.
        -   **Data Validation:** For backends or data processing, use a library like Pydantic to define and validate data models to prevent bad data from entering your system.
    """)