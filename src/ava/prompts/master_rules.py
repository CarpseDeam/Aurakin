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

# --- NEW: The Senior Architect Protocol ---
SENIOR_ARCHITECT_PROTOCOL = textwrap.dedent("""
    1.  **OBJECT-ORIENTED BY DEFAULT:**
        -   All state and related logic MUST be encapsulated within classes. Avoid procedural scripts with loose functions for anything beyond a simple, single-purpose tool.
        -   Identify the core nouns in the user request; these are your candidate classes (e.g., "Web Scraper" -> `WebScraper` class, "User Data" -> `User` class).

    2.  **MANDATORY PYDANTIC MODELS FOR DATA:**
        -   Any structured data that is passed between components or returned from functions MUST be defined as a `pydantic.BaseModel`. This is non-negotiable for data validation and clear contracts.

    3.  **CONFIGURATION & DEPENDENCY INJECTION:**
        -   **No Hard-coded Values:** Magic numbers, URLs, file paths, or API keys are forbidden. Plan for a dedicated configuration object or file (`config.py`).
        -   **Inject, Don't Create:** Components MUST receive their dependencies (like clients, services, or configuration objects) in their `__init__` method. They should NOT create their own dependencies internally. This is critical for testability and modularity.

    4.  **SINGLE RESPONSIBILITY & DRY:**
        -   Each class and module MUST have one, and only one, clear responsibility.
        -   If you identify a repeated task, plan for a shared utility module or a base class. Do not repeat logic.
""")

# --- RENAMED & REFINED: The protocol for file planning ---
FILE_PLANNER_PROTOCOL = textwrap.dedent("""
    **LAW: FILE PLANNING PROTOCOL - YOU MUST ADHERE TO THESE AT ALL TIMES.**

    1.  **MAINTAINABILITY & CLARITY:**
        -   **Single Responsibility Principle (SRP):** Every file should have one clear purpose, as dictated by the high-level architectural plan.
        -   **Descriptive Naming:** Use clear, unambiguous names for files and modules that reflect the components in the plan.
        -   **Modularity & Clean Entry Points:** Group related classes into modules. The main entry point (`main.py`) MUST be minimal.
        -   **The `main.py` file is ONLY a launcher.** Its sole purpose is to instantiate the main application class and run it, usually within a `if __name__ == "__main__":` block.

    2.  **PYTHON PACKAGING & TESTING:**
        -   For any source directory you create (like 'src', 'src/components'), you MUST include an `__init__.py` file.
        -   You MUST include a `requirements.txt` file in the root. At a minimum, it must contain `pytest`. If the plan calls for Pydantic, it must also be included.

    3.  **PROFESSIONAL INTERFACE CONTRACTS:**
        -   **Mandatory Type Hinting:** All function and method signatures in the `public_members` list MUST include type hints.
        -   **Comprehensive Docstrings:** The `purpose` for each file MUST be a comprehensive, Google-style module docstring explaining its role in the system.
""")

# --- (The S_TIER_ENGINEERING_PROTOCOL remains the same) ---
S_TIER_ENGINEERING_PROTOCOL = textwrap.dedent("""
    **LAW: S-TIER ENGINEERING PROTOCOL - YOU MUST ADHERE TO THESE AT ALL TIMES.**

    1.  **ROBUSTNESS & ERROR HANDLING:**
        -   **NEVER trust external inputs or resources.** Aggressively use `try...except` blocks for file operations (`FileNotFoundError`, `IOError`), network requests, and dictionary key access (`KeyError`).
        -   **Configuration Management:** For API keys or secrets, your code should read from environment variables using `os.getenv('MY_VARIABLE')`. Never hardcode secrets.
        -   **Graceful Failure:** Your code should anticipate potential failures and handle them gracefully, logging errors instead of crashing.

    2.  **MODERN & EFFICIENT PYTHON:**
        -   **Always prefer `pathlib.Path` over `os.path`** for all file system operations.
        -   **Use Dataclasses or Pydantic:** For data-holding objects, always prefer `@dataclass` for internal data or `pydantic.BaseModel` for data with validation and serialization needs.
        -   **Use F-strings:** All string formatting must use f-strings.
        -   **Dependency Management:** All external libraries MUST be listed in a `requirements.txt` file.

    3.  **CODE ELEGANCE & PYTHONIC STYLE:**
        -   **Minimalist Logic:** Strive for the clearest and most direct implementation. A simple loop is better than a complex, "clever" one-liner.
        -   **Context Managers:** Always use the `with` statement for resources like files or network connections.
        -   **Data-Driven Logic:** For mapping choices to actions (like calculator operations), prefer a dictionary lookup over a long `if/elif/else` chain.
        -   **Clarity over Brevity:** Write code that is easy for a human to read and understand.

    4.  **IDEMPOTENT & STATELESS LOGIC:**
        -   Functions should be stateless where possible. Given the same inputs, they should produce the same outputs.
        -   Classes should be initialized to a clean state. Avoid relying on module-level global variables.

    5.  **NO PLACEHOLDERS OR TODOs:**
        -   All generated code MUST be fully functional and complete.
        -   Do not include comments like `# TODO: Implement this later` or use `pass` in a function body unless it is a deliberate abstract method.
""")