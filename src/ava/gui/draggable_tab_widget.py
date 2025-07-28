# src/ava/gui/draggable_tab_widget.py
# NEW FILE
from PySide6.QtWidgets import QTabWidget, QTabBar
from PySide6.QtCore import Qt, QPoint, QMimeData, QUrl
from PySide6.QtGui import QMouseEvent, QDrag


class DraggableTabBar(QTabBar):
    """
    A custom QTabBar that initiates a drag operation with the file path
    when a tab is dragged.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dragStartPosition = QPoint()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragStartPosition = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.pos() - self.dragStartPosition).manhattanLength() < 15: # Start drag threshold
            return

        tab_index = self.tabAt(self.dragStartPosition)
        if tab_index < 0:
            return

        drag = QDrag(self)
        mime_data = QMimeData()

        # Get the full file path from the tab's tooltip
        file_path = self.tabToolTip(tab_index)
        if not file_path:
            return

        # Package the file path as a URL, which is the standard way
        # to represent local files for drag-and-drop.
        mime_data.setUrls([QUrl.fromLocalFile(file_path)])
        drag.setMimeData(mime_data)

        # Start the drag operation
        drag.exec(Qt.DropAction.CopyAction)


class DraggableTabWidget(QTabWidget):
    """
    A QTabWidget that uses our custom DraggableTabBar to enable
    dragging tabs out of the widget.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(DraggableTabBar(self))