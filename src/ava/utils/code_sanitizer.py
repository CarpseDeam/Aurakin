# src/ava/utils/code_sanitizer.py
# NEW FILE
import re

def sanitize_llm_code_output(raw_code: str) -> str:
    """
    A robust, step-by-step function to reliably remove markdown fences
    and optional language identifiers from LLM-generated code blocks.
    """
    if not isinstance(raw_code, str):
        return ""

    code = raw_code.strip()

    # Define common fences and language identifiers
    fences = ["```", "'''"]
    languages = ["python", "py"]

    # Step 1: Remove opening fence and optional language identifier
    for fence in fences:
        if code.startswith(fence):
            code = code[len(fence):].lstrip()
            # Check for language identifier on the same line or next line
            for lang in languages:
                if code.lower().startswith(lang):
                    code = code[len(lang):].lstrip()
            break  # Stop after processing the first found fence

    # Step 2: Remove closing fence
    for fence in fences:
        if code.endswith(fence):
            code = code[:-len(fence)].rstrip()
            break # Stop after processing

    return code