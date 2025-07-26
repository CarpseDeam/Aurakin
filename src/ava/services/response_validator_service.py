# src/ava/services/response_validator_service.py
import json
import re
from typing import Dict, Any, Optional, Union, List

class ResponseValidatorService:
    """
    A dedicated service to parse, clean, and validate responses from LLMs.
    Its single responsibility is to turn raw, unpredictable LLM string
    output into a predictable, usable Python object (dict or list).
    """

    def extract_and_parse_json(self, raw_response: str) -> Optional[Union[Dict, List]]:
        """
        Extracts a JSON object or list from a raw string and parses it.
        This function is robust against conversational text, markdown code fences, and truncation.
        """
        if not raw_response or not isinstance(raw_response, str):
            return None

        # Step 1: Find the content that is most likely to be the JSON payload.
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_response, re.DOTALL)
        content_to_parse = fence_match.group(1) if fence_match else raw_response

        # Step 2: Find the start of the first JSON object or array.
        first_brace = content_to_parse.find('{')
        first_bracket = content_to_parse.find('[')

        if first_brace == -1 and first_bracket == -1: return None

        if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
            start_pos = first_brace
        else:
            start_pos = first_bracket

        # Step 3: Parse character-by-character to find the end of the first complete object.
        # This is resilient to truncated streams by correctly balancing nested structures.
        delimiter_stack = []
        in_string = False
        is_escaped = False

        for i in range(start_pos, len(content_to_parse)):
            char = content_to_parse[i]

            if is_escaped:
                is_escaped = False
                continue

            if char == '\\':
                is_escaped = True
                continue

            if char == '"':
                in_string = not in_string

            if in_string:
                continue

            if char == '{' or char == '[':
                delimiter_stack.append(char)
            elif char == '}':
                if not delimiter_stack or delimiter_stack[-1] != '{':
                    # Malformed JSON, but we can't recover.
                    return None
                delimiter_stack.pop()
            elif char == ']':
                if not delimiter_stack or delimiter_stack[-1] != '[':
                    # Malformed JSON.
                    return None
                delimiter_stack.pop()

            if not delimiter_stack:
                # We have found the end of the top-level object.
                json_string = content_to_parse[start_pos : i + 1]
                try:
                    return json.loads(json_string)
                except json.JSONDecodeError:
                    return None

        # If we finish the loop and the stack is not empty, the JSON was truncated.
        return None

    def extract_json_from_tag(self, raw_response: str, tag: str) -> Optional[Union[Dict, List]]:
        """
        Extracts content from a specific XML-style tag and parses it as JSON.
        """
        if not raw_response or not isinstance(raw_response, str):
            return None

        pattern = re.compile(f"<{tag}>(.*?)</{tag}>", re.DOTALL)
        match = pattern.search(raw_response)

        if not match:
            return None

        content_to_parse = match.group(1).strip()
        # Now we can reuse our existing robust JSON parser on this smaller string
        return self.extract_and_parse_json(content_to_parse)

    def _clean_scaffold_paths(self, scaffold: Dict[str, str]) -> Dict[str, str]:
        """
        Detects and removes a spurious common base directory from scaffold keys.
        e.g., {"AppName/main.py": "..."} becomes {"main.py": "..."}
        """
        if not scaffold:
            return scaffold

        paths = list(scaffold.keys())
        # Check if there are any paths with directory separators
        paths_in_dirs = [p for p in paths if '/' in p.replace('\\', '/')]
        if not paths_in_dirs:
            return scaffold # No directories, nothing to clean

        # Get the first part of the first path with a directory
        path_parts = [p.replace('\\', '/').split('/') for p in paths_in_dirs]
        first_part = path_parts[0][0]
        if not first_part:
            return scaffold # Path starts with a slash, not a directory name

        # Check if ALL paths with directories start with the same first part
        if all(p[0] == first_part for p in path_parts):
            cleaned_scaffold = {}
            for original_path, content in scaffold.items():
                parts = original_path.replace('\\', '/').split('/')
                # Clean paths that have the common base directory
                if len(parts) > 1 and parts[0] == first_part:
                    new_path = '/'.join(parts[1:])
                    cleaned_scaffold[new_path] = content
                else:
                    # Keep paths that don't match the pattern as-is
                    cleaned_scaffold[original_path] = content
            return cleaned_scaffold

        return scaffold

    def _find_file_dict_recursively(self, data: Any) -> Optional[Dict[str, str]]:
        """
        Recursively searches through a nested data structure for the first
        dictionary that looks like a file scaffold.
        """
        # Base case: Is the current data a valid-looking file dictionary?
        if isinstance(data, dict) and data:
            # Heuristic: check if keys look like file paths and values are strings
            is_plausible = all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
            if is_plausible:
                 # Additional heuristic to avoid matching simple metadata dicts
                if any(ext in path for path in data.keys() for ext in ['.py', '.txt', '.md', '.json', '.gitignore']):
                    return data

        # Base case: Is the current data a valid-looking list of file objects?
        if isinstance(data, list) and data:
            if all(isinstance(item, dict) and "filename" in item and "content" in item for item in data):
                try:
                    return {item["filename"]: item["content"] for item in data}
                except Exception:
                    pass  # Ignore malformed items

        # Recursive step for dictionaries
        if isinstance(data, dict):
            for key, value in data.items():
                result = self._find_file_dict_recursively(value)
                if result:
                    return result

        # Recursive step for lists
        if isinstance(data, list):
            for item in data:
                result = self._find_file_dict_recursively(item)
                if result:
                    return result

        return None

    def validate_and_flatten_scaffold(self, parsed_json: Optional[Union[Dict, List]]) -> Optional[Dict[str, str]]:
        """
        Validates and flattens a scaffold response into a clean Dict[str, str].
        This now intelligently searches the entire JSON structure for the file dictionary.
        """
        if not parsed_json:
            return None

        # The new recursive search will find the file dictionary no matter how nested it is.
        found_scaffold = self._find_file_dict_recursively(parsed_json)

        if found_scaffold:
            return self._clean_scaffold_paths(found_scaffold)

        return None