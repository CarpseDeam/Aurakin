# src/ava/prompts/master_rules.py
import textwrap

# This rule is for any agent that must return a JSON object.
JSON_OUTPUT_RULE = """
**LAW: STRICT JSON OUTPUT**
- Your entire response MUST be a single, valid JSON object.
- Do not add any conversational text, explanations, or markdown before or after the JSON object.
- Your response must begin with `{{` and end with `}}`.
"""

# This rule is for any code-writing agent.
RAW_CODE_OUTPUT_RULE = """
**LAW: RAW CODE OUTPUT ONLY**
- Your entire response MUST be only the raw code for the assigned file.
- Do not write any explanations, comments, or markdown before or after the code.
"""

# --- NEW: ARCHITECT'S PROTOCOL (Design & Structure) ---
ARCHITECT_DESIGN_PROTOCOL = textwrap.dedent("""
    **LAW: ARCHITECTURAL DESIGN PROTOCOL - YOU MUST ADHERE TO THESE AT ALL TIMES.**

    1.  **MAINTAINABILITY & CLARITY:**
        -   **Single Responsibility Principle (SRP):** Every file should have one clear purpose.
        -   **Descriptive Naming:** Use clear, unambiguous names for files and modules.
        -   **Modularity & Clean Entry Points:** Group related functions into modules. The main entry point (`main.py`) MUST be minimal; its only job is to initialize and run the application. Core logic, especially user interaction loops (`input()`/`print()`), MUST be in separate modules (e.g., a `ui` or `cli` module).

    2.  **PROFESSIONAL SIGNATURES:**
        -   **Mandatory Type Hinting:** All function and method signatures MUST include type hints for all arguments and for the return value. Use the `typing` module where necessary.
        -   **Comprehensive Docstrings:** Every module, class, and public function MUST have a comprehensive, Google-style docstring. Module docstrings describe the file's purpose. Function/method docstrings must describe the purpose, `Args:`, and `Returns:`.
""")

# --- UPDATED: CODER'S PROTOCOL (Now includes ELEGANCE) ---
S_TIER_ENGINEERING_PROTOCOL = textwrap.dedent("""
    **LAW: S-TIER ENGINEERING PROTOCOL - YOU MUST ADHERE TO THESE AT ALL TIMES.**

    1.  **ROBUSTNESS & ERROR HANDLING:**
        -   **NEVER trust external inputs or resources.** Aggressively use `try...except` blocks for file operations (`FileNotFoundError`, `IOError`), network requests, and dictionary key access (`KeyError`).
        -   **Configuration Management:** For API keys or secrets, your code should read from environment variables using `os.getenv('MY_VARIABLE')`. Never hardcode secrets.
        -   **Graceful Failure:** Your code should anticipate potential failures and handle them gracefully, logging errors instead of crashing.

    2.  **MODERN & EFFICIENT PYTHON:**
        -   **Always prefer `pathlib.Path` over `os.path`** for all file system operations.
        -   **Use Dataclasses:** For simple data-holding objects, always prefer `@dataclass`.
        -   **Use F-strings:** All string formatting must use f-strings.
        -   **Dependency Management:** All external libraries MUST be listed in a `requirements.txt` file.

    3.  **CODE ELEGANCE & PYTHONIC STYLE:**
        -   **Minimalist Logic:** Strive for the clearest and most direct implementation. A simple loop is better than a complex, "clever" one-liner.
        -   **Context Managers:** Always use the `with` statement for resources like files or network connections.
        -   **Data-Driven Logic:** For mapping choices to actions (like calculator operations), prefer a dictionary lookup over a long `if/elif/else` chain.
        -   **Clarity over Brevity:** Write code that is easy for a human to read and understand.
""")