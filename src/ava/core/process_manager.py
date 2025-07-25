# src/ava/core/process_manager.py
# NEW FILE
import subprocess
from typing import List, Tuple

# A module-level list to hold tuples of (process_object, process_name),
# acting as a simple, effective singleton.
_managed_processes: List[Tuple[subprocess.Popen, str]] = []


def register(process: subprocess.Popen, name: str):
    """Registers a new process to be managed."""
    if process and isinstance(process, subprocess.Popen):
        pid = process.pid if process else 'N/A'
        print(f"[ProcessManager] Registering process '{name}' with PID: {pid}")
        _managed_processes.append((process, name))
    else:
        print(f"[ProcessManager] WARNING: Attempted to register an invalid process object for '{name}'.")


def terminate_all():
    """Terminates all registered child processes."""
    print(f"[ProcessManager] Terminating all {len(_managed_processes)} registered processes...")

    if not _managed_processes:
        print("[ProcessManager] No processes to terminate.")
        return

    for process, name in _managed_processes:
        # Check if the process is still running before trying to terminate it.
        if process.poll() is None:
            print(f"[ProcessManager] Terminating '{name}' (PID: {process.pid})...")
            try:
                # Use kill() for forceful termination, which is what the original code did
                # and what's needed for these detached server processes.
                process.kill()
                # Wait for the process to die to avoid zombies.
                process.wait(timeout=3)
                print(f"[ProcessManager] Process '{name}' (PID: {process.pid}) terminated successfully.")
            except subprocess.TimeoutExpired:
                print(f"[ProcessManager] WARNING: Process '{name}' (PID: {process.pid}) did not terminate in time.")
            except Exception as e:
                print(f"[ProcessManager] ERROR: Could not terminate process '{name}' (PID: {process.pid}): {e}")
        else:
            # This is not an error, just informational.
            pid = process.pid if process else 'N/A'
            print(f"[ProcessManager] Process '{name}' (PID: {pid}) was already terminated.")

    _managed_processes.clear()
    print("[ProcessManager] Process termination sequence complete.")