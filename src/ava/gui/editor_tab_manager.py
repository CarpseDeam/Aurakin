# src/ava/gui/editor_tab_manager.py
import asyncio
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
        self.lsp_client = None  # Will be set from CodeViewerWindow
        self._setup_initial_state()
        self._connect_events()

    def set_lsp_client(self, lsp_client):
        """Sets the LSP client instance for communication."""
        self.lsp_client = lsp_client

    def _connect_events(self):
        self.event_bus.subscribe("file_renamed", self._handle_file_renamed)
        self.event_bus.subscribe("items_deleted", self._handle_items_deleted)
        self.event_bus.subscribe("items_moved", self._handle_items_moved)
        self.event_bus.subscribe("items_added", self._handle_items_added)
        # --- NEW: Surgical Edit Animation Events ---
        self.event_bus.subscribe("highlight_lines_for_edit", self._handle_highlight_lines)
        self.event_bus.subscribe("delete_highlighted_lines", self._handle_delete_lines)
        self.event_bus.subscribe("position_cursor_for_insert", self._handle_position_cursor)

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

    def create_or_update_tab(self, abs_path_str: str, content: str):
        if abs_path_str not in self.editors:
            self.create_editor_tab(abs_path_str)
        self.set_editor_content(abs_path_str, content)
        self.focus_tab(abs_path_str)

    def create_editor_tab(self, abs_path_str: str) -> bool:
        if abs_path_str in self.editors:
            self.focus_tab(abs_path_str)
            return False

        if self.tab_widget.count() == 1 and isinstance(self.tab_widget.widget(0), QLabel):
            self.tab_widget.removeTab(0)

        editor = EnhancedCodeEditor()
        if abs_path_str.endswith('.py'):
            PythonHighlighter(editor.document())
        elif abs_path_str.endswith('.gd'):
            GenericHighlighter(editor.document(), 'gdscript')

        editor.save_requested.connect(lambda: self.save_file(abs_path_str))
        editor.content_changed.connect(lambda: self._update_tab_title(abs_path_str))

        tab_index = self.tab_widget.addTab(editor, Path(abs_path_str).name)
        self.tab_widget.setTabToolTip(tab_index, abs_path_str)
        self.editors[abs_path_str] = editor
        print(f"[EditorTabManager] Created enhanced editor tab for: {abs_path_str}")
        return True

    def set_editor_content(self, abs_path_str: str, content: str):
        if abs_path_str in self.editors:
            editor = self.editors[abs_path_str]
            editor.set_content(content)
            self._update_tab_title(abs_path_str)
            if self.lsp_client:
                asyncio.create_task(self.lsp_client.did_open(abs_path_str, content))

    def stream_content_to_editor(self, abs_path_str: str, chunk: str):
        if abs_path_str not in self.editors:
            if not self.create_editor_tab(abs_path_str):
                pass
            self.focus_tab(abs_path_str)

        editor = self.editors.get(abs_path_str)
        if editor:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(chunk)
            editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())

    def focus_tab(self, abs_path_str: str):
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabToolTip(i) == abs_path_str:
                self.tab_widget.setCurrentIndex(i)
                return True
        return False

    def open_file_in_tab(self, file_path: Path):
        if not file_path.is_file(): return
        abs_path_str = str(file_path.resolve())
        if abs_path_str in self.editors:
            self.focus_tab(abs_path_str)
            return

        try:
            content = file_path.read_text(encoding='utf-8')
            self.create_or_update_tab(abs_path_str, content)
        except Exception as e:
            print(f"[EditorTabManager] Error opening file {file_path}: {e}")
            QMessageBox.warning(self.tab_widget, "Open File Error", f"Could not open file:\n{file_path.name}\n\n{e}")

    def close_tab(self, index: int, force_close: bool = False):
        abs_path_str = self.tab_widget.tabToolTip(index)
        widget_to_remove = self.tab_widget.widget(index)

        if abs_path_str in self.editors:
            editor = self.editors[abs_path_str]
            if not force_close and editor.is_dirty():
                reply = QMessageBox.question(self.tab_widget, "Unsaved Changes",
                                             f"File '{Path(abs_path_str).name}' has unsaved changes. Save before closing?",
                                             QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Save:
                    if not self.save_file(abs_path_str):
                        return
                elif reply == QMessageBox.StandardButton.Cancel:
                    return

            if self.lsp_client:
                asyncio.create_task(self.lsp_client.did_close(abs_path_str))

            del self.editors[abs_path_str]

        self.tab_widget.removeTab(index)
        if widget_to_remove:
            widget_to_remove.deleteLater()

        if self.tab_widget.count() == 0:
            self._add_welcome_tab("All tabs closed. Open a file or generate code.")

    def save_file(self, abs_path_str: str) -> bool:
        if abs_path_str not in self.editors: return False
        editor = self.editors[abs_path_str]
        try:
            file_path = Path(abs_path_str)
            content = editor.toPlainText()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
            editor.mark_clean()
            self._update_tab_title(abs_path_str)
            if self.project_manager and self.project_manager.active_project_path:
                rel_path = file_path.relative_to(self.project_manager.active_project_path).as_posix()
                self.project_manager.stage_file(rel_path)
            return True
        except Exception as e:
            self._show_save_error(Path(abs_path_str).name, str(e))
            return False

    def save_current_file(self) -> bool:
        current_path = self.get_active_file_path()
        if current_path:
            return self.save_file(current_path)
        return False

    def save_all_files(self) -> bool:
        all_saved = True
        for abs_path_str in list(self.editors.keys()):
            editor = self.editors.get(abs_path_str)
            if editor and editor.is_dirty():
                if not self.save_file(abs_path_str):
                    all_saved = False
        return all_saved

    def has_unsaved_changes(self) -> bool:
        return any(editor.is_dirty() for editor in self.editors.values())

    def _update_tab_title(self, abs_path_str: str):
        if abs_path_str not in self.editors: return
        editor = self.editors[abs_path_str]
        base_name = Path(abs_path_str).name
        title = f"{'*' if editor.is_dirty() else ''}{base_name}"
        for i in range(self.tab_widget.count()):
            if self.tab_widget.tabToolTip(i) == abs_path_str:
                self.tab_widget.setTabText(i, title)
                break

    def _show_save_error(self, filename: str, error: str):
        QMessageBox.critical(self.tab_widget, "Save Error", f"Could not save '{filename}'\nError: {error}")

    def handle_diagnostics(self, uri: str, diagnostics: List[Dict[str, Any]]):
        try:
            file_path = Path(uri.replace("file:///", "").replace("%3A", ":")).resolve()
            abs_path_str = str(file_path)
            if abs_path_str in self.editors:
                self.editors[abs_path_str].set_diagnostics(diagnostics)
        except Exception as e:
            print(f"[EditorTabManager] Error handling diagnostics for {uri}: {e}")
            
    def _get_editor_for_filename(self, filename: str) -> Optional[EnhancedCodeEditor]:
        if not self.project_manager or not self.project_manager.active_project_path:
            return None
        abs_path_str = str((self.project_manager.active_project_path / filename).resolve())
        editor = self.editors.get(abs_path_str)
        if editor:
            self.focus_tab(abs_path_str)
        return editor

    def _handle_highlight_lines(self, filename: str, start_line: int, end_line: int):
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.highlight_line_range(start_line, end_line)

    def _handle_delete_lines(self, filename: str):
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.delete_highlighted_range()

    def _handle_position_cursor(self, filename: str, line: int, col: int):
        editor = self._get_editor_for_filename(filename)
        if editor:
            editor.set_cursor_position(line, col)

    def _handle_file_renamed(self, old_rel_path_str: str, new_rel_path_str: str):
        if not self.project_manager or not self.project_manager.active_project_path: return
        old_abs_path_str = str((self.project_manager.active_project_path / old_rel_path_str).resolve())
        new_abs_path_str = str((self.project_manager.active_project_path / new_rel_path_str).resolve())
        if old_abs_path_str in self.editors:
            editor = self.editors.pop(old_abs_path_str)
            self.editors[new_abs_path_str] = editor
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabToolTip(i) == old_abs_path_str:
                    new_tab_name = Path(new_abs_path_str).name
                    self.tab_widget.setTabText(i, new_tab_name + ("*" if editor.is_dirty() else ""))
                    self.tab_widget.setTabToolTip(i, new_abs_path_str)
                    break

    def _handle_items_deleted(self, deleted_rel_paths: List[str]):
        if not self.project_manager or not self.project_manager.active_project_path: return
        abs_paths_to_check = {str((self.project_manager.active_project_path / p).resolve()) for p in deleted_rel_paths}
        tabs_to_close = []
        for i in range(self.tab_widget.count()):
            tab_path = self.tab_widget.tabToolTip(i)
            if tab_path in abs_paths_to_check:
                tabs_to_close.append(i)
        for i in sorted(tabs_to_close, reverse=True):
            self.close_tab(i, force_close=True)

    def _handle_items_moved(self, moved_item_infos: List[Dict[str, str]]):
        if not self.project_manager or not self.project_manager.active_project_path: return
        for info in moved_item_infos:
            old_abs = str((self.project_manager.active_project_path / info['old']).resolve())
            new_abs = str((self.project_manager.active_project_path / info['new']).resolve())
            if old_abs in self.editors:
                editor = self.editors.pop(old_abs)
                self.editors[new_abs] = editor
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabToolTip(i) == old_abs:
                        self.tab_widget.setTabText(i, Path(new_abs).name + ("*" if editor.is_dirty() else ""))
                        self.tab_widget.setTabToolTip(i, new_abs)
                        break

    def _handle_items_added(self, added_item_infos: List[Dict[str, str]]):
        if not self.project_manager or not self.project_manager.active_project_path: return
        for info in added_item_infos:
            abs_path = str((self.project_manager.active_project_path / info['new_project_rel_path']).resolve())
            self.open_file_in_tab(Path(abs_path))