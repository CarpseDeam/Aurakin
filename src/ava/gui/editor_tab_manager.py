# src/ava/gui/editor_tab_manager.py
import asyncio
import os
from pathlib import Path
from typing import Dict, Optional, List, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTabWidget, QLabel, QWidget, QMessageBox

from src.ava.gui.enhanced_code_editor import EnhancedCodeEditor
from src.ava.gui.components import Colors, Typography
from src.ava.gui.code_viewer_helpers import PythonHighlighter, GenericHighlighter
from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager


class EditorTabManager:
    """Manages editor tabs with enhanced code editors and file saving."""

    def __init__(self, tab_widget: QTabWidget, event_bus: EventBus, project_manager: ProjectManager):
        self.tab_widget = tab_widget
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.editors: Dict[str, EnhancedCodeEditor] = {}
        self.lsp_client = None
        self._is_generating = False
        self._setup_initial_state()
        self._connect_events()

    def _resolve_and_normalize_path(self, path_str: str) -> Optional[str]:
        """Resolves a given path (relative or absolute) against the project root and normalizes it for cross-platform key consistency."""
        path = Path(path_str)
        if not path.is_absolute():
            if self.project_manager and self.project_manager.active_project_path:
                path = self.project_manager.active_project_path / path
            else:
                return None
        return os.path.normcase(str(path.resolve()))

    def set_lsp_client(self, lsp_client):
        """Sets the LSP client instance for communication."""
        self.lsp_client = lsp_client

    def _connect_events(self):
        self.event_bus.subscribe("file_renamed", self._handle_file_renamed)
        self.event_bus.subscribe("items_deleted", self._handle_items_deleted)
        self.event_bus.subscribe("items_moved", self._handle_items_moved)
        self.event_bus.subscribe("items_added", self._handle_items_added)

    def _setup_initial_state(self):
        self.clear_all_tabs()
        self._add_welcome_tab("Code will appear here when generated.")

    def _add_welcome_tab(self, message: str):
        welcome_label = QLabel(message)
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label.setFont(Typography.get_font(18))
        welcome_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY.name()};")
        self.tab_widget.addTab(welcome_label, "Welcome")

    def prepare_for_new_project(self):
        if self.has_unsaved_changes():
            reply = QMessageBox.question(self.tab_widget, "Unsaved Changes",
                                         "You have unsaved changes. Save them before creating a new project?",
                                         QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self.save_all_files()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        self.clear_all_tabs()
        self._add_welcome_tab("Ready for new project generation...")
        print("[EditorTabManager] State reset for new project session.")

    def clear_all_tabs(self):
        while self.tab_widget.count() > 0:
            widget_to_remove = self.tab_widget.widget(0)
            self.tab_widget.removeTab(0)
            if widget_to_remove in self.editors.values():
                path_key_to_remove = None
                for key, editor_instance in self.editors.items():
                    if editor_instance == widget_to_remove:
                        path_key_to_remove = key
                        break
                if path_key_to_remove:
                    del self.editors[path_key_to_remove]
            if widget_to_remove:
                widget_to_remove.deleteLater()
        self.editors.clear()

    def get_active_file_path(self) -> Optional[str]:
        current_index = self.tab_widget.currentIndex()
        if current_index == -1: return None
        return self.tab_widget.tabToolTip(current_index)

    def create_or_update_tab(self, path_str: str, content: str):
        norm_path = self._resolve_and_normalize_path(path_str)
        if not norm_path:
            print(f"[EditorTabManager] Could not resolve path for tab: {path_str}")
            return

        if norm_path not in self.editors:
            self.create_editor_tab(norm_path)
        self.set_editor_content(norm_path, content)
        # We no longer automatically focus here, we let the display_final_files method handle it.
        # self.focus_tab(norm_path)

    def display_final_files(self, files_to_display: Dict[str, str]):
        """
        Clears existing tabs and displays only the specified files.
        This is the primary method for showing generation results.
        """
        self.clear_all_tabs()
        if not files_to_display:
            self._add_welcome_tab("No files were changed in this modification.")
            return

        first_file_path = None
        for path_str, content in files_to_display.items():
            if first_file_path is None:
                first_file_path = self._resolve_and_normalize_path(path_str)
            self.create_or_update_tab(path_str, content)

        if first_file_path:
            self.focus_tab(first_file_path)

    def create_editor_tab(self, norm_path_str: str) -> bool:
        if norm_path_str in self.editors:
            self.focus_tab(norm_path_str)
            return False

        if self.tab_widget.count() == 1 and isinstance(self.tab_widget.widget(0), QLabel):
            self.tab_widget.removeTab(0)

        editor = EnhancedCodeEditor()
        if norm_path_str.endswith('.py'):
            PythonHighlighter(editor.document())
        elif norm_path_str.endswith('.gd'):
            GenericHighlighter(editor.document(), 'gdscript')

        editor.save_requested.connect(lambda: self.save_file(norm_path_str))
        editor.content_changed.connect(lambda: self._update_tab_title(norm_path_str))

        tab_index = self.tab_widget.addTab(editor, Path(norm_path_str).name)
        self.tab_widget.setTabToolTip(tab_index, norm_path_str)
        self.editors[norm_path_str] = editor
        print(f"[EditorTabManager] Created enhanced editor tab for: {norm_path_str}")
        return True

    def set_editor_content(self, norm_path_str: str, content: str):
        if norm_path_str in self.editors:
            editor = self.editors[norm_path_str]

            scrollbar = editor.verticalScrollBar()
            original_scroll_value = scrollbar.value()

            old_content = editor.toPlainText()
            old_line_count = old_content.count('\n')
            new_line_count = content.count('\n')
            line_diff = new_line_count - old_line_count

            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(content)
            cursor.endEditBlock()

            editor._original_content = content
            editor._is_dirty = False

            if original_scroll_value == scrollbar.maximum() or original_scroll_value == 0:
                pass
            else:
                line_height = editor.fontMetrics().height()
                scrollbar.setValue(original_scroll_value + (line_diff * line_height))

            self._update_tab_title(norm_path_str)
            if self.lsp_client:
                asyncio.create_task(self.lsp_client.did_open(norm_path_str, content))

    def stream_content_to_editor(self, filename: str, chunk: str):
        norm_path = self._resolve_and_normalize_path(filename)
        if not norm_path:
            print(f"[EditorTabManager] Could not resolve path for streaming: {filename}")
            return

        if norm_path not in self.editors:
            if not self.create_editor_tab(norm_path):
                return
            self.focus_tab(norm_path)

        editor = self.editors.get(norm_path)
        if editor:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(chunk)
            editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())

    def focus_tab(self, norm_path_str: str):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabToolTip(i) == norm_path_str:
                self.tab_widget.setCurrentIndex(i)
                return True
        return False

    def open_file_in_tab(self, file_path: Path):
        if not file_path.is_file(): return
        norm_path_str = self._resolve_and_normalize_path(str(file_path))
        if not norm_path_str: return

        if norm_path_str in self.editors:
            self.focus_tab(norm_path_str)
            return

        try:
            content = file_path.read_text(encoding='utf-8')
            self.create_or_update_tab(norm_path_str, content)
            self.focus_tab(norm_path_str)
        except Exception as e:
            print(f"[EditorTabManager] Error opening file {file_path}: {e}")
            QMessageBox.warning(self.tab_widget, "Open File Error", f"Could not open file:\n{file_path.name}\n\n{e}")

    def close_tab(self, index: int, force_close: bool = False):
        norm_path_str = self.tab_widget.tabToolTip(index)
        widget_to_remove = self.tab_widget.widget(index)

        if norm_path_str and norm_path_str in self.editors:
            editor = self.editors[norm_path_str]
            if not force_close and editor.is_dirty():
                reply = QMessageBox.question(self.tab_widget, "Unsaved Changes",
                                             f"File '{Path(norm_path_str).name}' has unsaved changes. Save before closing?",
                                             QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Save:
                    if not self.save_file(norm_path_str):
                        return
                elif reply == QMessageBox.StandardButton.Cancel:
                    return

            if self.lsp_client:
                asyncio.create_task(self.lsp_client.did_close(norm_path_str))

            del self.editors[norm_path_str]

        self.tab_widget.removeTab(index)
        if widget_to_remove:
            widget_to_remove.deleteLater()

        if self.tab_widget.count() == 0:
            self._add_welcome_tab("All tabs closed. Open a file or generate code.")

    def save_file(self, norm_path_str: str) -> bool:
        if norm_path_str not in self.editors: return False
        editor = self.editors[norm_path_str]
        try:
            file_path = Path(norm_path_str)
            content = editor.toPlainText()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
            editor.mark_clean()
            self._update_tab_title(norm_path_str)
            if self.project_manager and self.project_manager.active_project_path:
                rel_path = file_path.relative_to(self.project_manager.active_project_path).as_posix()
                self.project_manager.stage_file(rel_path)
            return True
        except Exception as e:
            self._show_save_error(Path(norm_path_str).name, str(e))
            return False

    def save_current_file(self) -> bool:
        current_path = self.get_active_file_path()
        if current_path:
            return self.save_file(current_path)
        return False

    def save_all_files(self) -> bool:
        all_saved = True
        for norm_path_str in list(self.editors.keys()):
            editor = self.editors.get(norm_path_str)
            if editor and editor.is_dirty():
                if not self.save_file(norm_path_str):
                    all_saved = False
        return all_saved

    def has_unsaved_changes(self) -> bool:
        return any(editor.is_dirty() for editor in self.editors.values())

    def _update_tab_title(self, norm_path_str: str):
        if norm_path_str not in self.editors: return
        editor = self.editors[norm_path_str]
        base_name = Path(norm_path_str).name
        title = f"{'*' if editor.is_dirty() else ''}{base_name}"
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabToolTip(i) == norm_path_str:
                self.tab_widget.setTabText(i, title)
                break

    def _show_save_error(self, filename: str, error: str):
        QMessageBox.critical(self.tab_widget, "Save Error", f"Could not save '{filename}'\nError: {error}")

    def handle_diagnostics(self, uri: str, diagnostics: List[Dict[str, Any]]):
        if self._is_generating:
            return

        try:
            file_path = Path(uri.replace("file:///", "").replace("%3A", ":"))
            norm_path_str = os.path.normcase(str(file_path.resolve()))
            if norm_path_str in self.editors:
                self.editors[norm_path_str].set_diagnostics(diagnostics)
        except Exception as e:
            print(f"[EditorTabManager] Error handling diagnostics for {uri}: {e}")

    def _get_editor_for_filename(self, filename: str) -> Optional[EnhancedCodeEditor]:
        norm_path = self._resolve_and_normalize_path(filename)
        if not norm_path: return None

        editor = self.editors.get(norm_path)
        if editor:
            self.focus_tab(norm_path)
        return editor

    def handle_highlight_lines(self, filename: str, start_line: int, end_line: int):
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.highlight_line_range(start_line, end_line)

    def handle_delete_lines(self, filename: str):
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.delete_highlighted_range()

    def handle_position_cursor(self, filename: str, line: int, col: int):
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.set_cursor_position(line, col)

    def handle_stream_at_cursor(self, filename: str, chunk: str):
        """Handles streaming text insertion at the current cursor position."""
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.insertPlainText(chunk)
            editor.ensureCursorVisible()

    def handle_finalize_content(self, filename: str):
        """Marks the editor's current content as 'clean' or 'saved'."""
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.mark_clean()

    def set_generating_state(self, is_generating: bool):
        """Controls whether to suppress LSP diagnostics."""
        print(f"[EditorTabManager] Setting generating state to: {is_generating}")
        self._is_generating = is_generating
        if not is_generating:
            for path_str, editor in self.editors.items():
                editor.set_diagnostics([])
                asyncio.create_task(self.lsp_client.did_open(path_str, editor.toPlainText()))
        else:
            for editor in self.editors.values():
                editor.set_diagnostics([])

    def _handle_file_renamed(self, old_rel_path_str: str, new_rel_path_str: str):
        old_norm_path = self._resolve_and_normalize_path(old_rel_path_str)
        new_norm_path = self._resolve_and_normalize_path(new_rel_path_str)
        if not old_norm_path or not new_norm_path: return

        if old_norm_path in self.editors:
            editor = self.editors.pop(old_norm_path)
            self.editors[new_norm_path] = editor
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabToolTip(i) == old_norm_path:
                    new_tab_name = Path(new_norm_path).name
                    self.tab_widget.setTabText(i, new_tab_name + ("*" if editor.is_dirty() else ""))
                    self.tab_widget.setTabToolTip(i, new_norm_path)
                    break

    def _handle_items_deleted(self, deleted_rel_paths: List[str]):
        paths_to_check = {self._resolve_and_normalize_path(p) for p in deleted_rel_paths}
        tabs_to_close = []
        for i in range(self.tab_widget.count()):
            tab_path = self.tab_widget.tabToolTip(i)
            if tab_path in paths_to_check:
                tabs_to_close.append(i)
        for i in sorted(tabs_to_close, reverse=True):
            self.close_tab(i, force_close=True)

    def _handle_items_moved(self, moved_item_infos: List[Dict[str, str]]):
        for info in moved_item_infos:
            old_norm_path = self._resolve_and_normalize_path(info['old'])
            new_norm_path = self._resolve_and_normalize_path(info['new'])
            if not old_norm_path or not new_norm_path: continue

            if old_norm_path in self.editors:
                editor = self.editors.pop(old_norm_path)
                self.editors[new_norm_path] = editor
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabToolTip(i) == old_norm_path:
                        self.tab_widget.setTabText(i, Path(new_norm_path).name + ("*" if editor.is_dirty() else ""))
                        self.tab_widget.setTabToolTip(i, new_norm_path)
                        break

    def _handle_items_added(self, added_item_infos: List[Dict[str, str]]):
        for info in added_item_infos:
            norm_path = self._resolve_and_normalize_path(info['new_project_rel_path'])
            if norm_path:
                self.open_file_in_tab(Path(norm_path))