# src/ava/gui/model_config_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QMessageBox, QFrame
)
from PySide6.QtGui import QFont

from src.ava.gui.components import Colors, Typography, ModernButton, TemperatureSlider
from src.ava.core.llm_client import LLMClient


class ModelConfigurationDialog(QDialog):
    def __init__(self, llm_client: LLMClient, parent=None):
        super().__init__(parent)
        self.llm_client = llm_client
        self.setWindowTitle("Configure AI Models")
        self.setMinimumSize(600, 450)
        self.setStyleSheet(f"background-color: {Colors.SECONDARY_BG.name()};")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Title
        title = QLabel("AI Specialist Configuration")
        title.setFont(Typography.get_font(16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY.name()};")
        main_layout.addWidget(title)

        # Store UI components
        self.role_combos = {}
        self.temperature_sliders = {}

        # Create role configuration sections
        roles_to_configure = ["architect", "coder", "chat"]
        for role in roles_to_configure:
            role_frame = self._create_role_configuration_frame(role.title(), role)
            main_layout.addWidget(role_frame)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = ModernButton("Cancel", "secondary")
        cancel_button.clicked.connect(self.reject)

        apply_button = ModernButton("Apply", "primary")
        apply_button.clicked.connect(self.apply_changes)

        button_layout.addWidget(cancel_button)
        button_layout.addWidget(apply_button)
        main_layout.addLayout(button_layout)

    def _create_role_configuration_frame(self, role_display_name: str, role_key: str) -> QFrame:
        """
        Create a frame containing model selection and temperature controls for a role.
        """
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.PRIMARY_BG.name()};
                border: 1px solid {Colors.BORDER_DEFAULT.name()};
                border-radius: 8px;
                padding: 10px;
            }}
        """)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(15, 15, 15, 15)
        frame_layout.setSpacing(10)

        role_title = QLabel(f"{role_display_name} Configuration")
        role_title.setFont(Typography.heading_small())
        role_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY.name()}; border: none; padding: 0;")
        frame_layout.addWidget(role_title)

        model_layout = QHBoxLayout()
        model_label = QLabel("Model:")
        model_label.setFont(Typography.body())
        model_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY.name()}; min-width: 80px;")

        model_combo = QComboBox()
        model_combo.setFont(Typography.body())
        model_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {Colors.ELEVATED_BG.name()};
                color: {Colors.TEXT_PRIMARY.name()};
                border: 1px solid {Colors.BORDER_DEFAULT.name()};
                border-radius: 4px;
                padding: 5px;
                min-width: 200px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {Colors.TEXT_SECONDARY.name()};
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {Colors.ELEVATED_BG.name()};
                color: {Colors.TEXT_PRIMARY.name()};
                selection-background-color: {Colors.ACCENT_BLUE.name()};
                border: 1px solid {Colors.BORDER_DEFAULT.name()};
            }}
        """)

        model_layout.addWidget(model_label)
        model_layout.addWidget(model_combo)
        model_layout.addStretch()
        frame_layout.addLayout(model_layout)

        temp_slider = TemperatureSlider()
        temp_slider.setStyleSheet("border: none; padding: 0;")
        frame_layout.addWidget(temp_slider)

        self.role_combos[role_key] = model_combo
        self.temperature_sliders[role_key] = temp_slider

        return frame

    def populate_settings(self):
        """Populate the dialog with current model and temperature settings."""
        current_assignments = self.llm_client.get_role_assignments()
        current_temperatures = self.llm_client.get_role_temperatures()

        for role, combo in self.role_combos.items():
            current_model_key = current_assignments.get(role)
            index = combo.findData(current_model_key)
            if index != -1:
                combo.setCurrentIndex(index)
            elif combo.count() > 0:
                combo.setCurrentIndex(0)

            if role in self.temperature_sliders:
                current_temp = current_temperatures.get(role, 0.7)
                self.temperature_sliders[role].set_temperature(current_temp)

    async def populate_models_async(self):
        """Asynchronously fetch available models and populate dropdowns."""
        available_models = await self.llm_client.get_available_models()
        if not available_models:
            QMessageBox.warning(
                self, "No Models Found",
                "Could not find any configured or local AI models. Please check your .env file or Ollama server."
            )
        for combo in self.role_combos.values():
            combo.clear()
            for key, name in available_models.items():
                combo.addItem(name, key)

    def apply_changes(self):
        """Apply the model and temperature changes."""
        try:
            new_assignments = {}
            for role, combo in self.role_combos.items():
                if combo.currentData() is not None:
                    new_assignments[role] = combo.currentData()

            # Since reviewer is gone, let's just map architect to it for safety
            if 'architect' in new_assignments:
                new_assignments['reviewer'] = new_assignments['architect']

            new_temperatures = {}
            for role, slider in self.temperature_sliders.items():
                new_temperatures[role] = slider.get_temperature()

            self.llm_client.set_role_assignments(new_assignments)
            self.llm_client.set_role_temperatures(new_temperatures)
            self.llm_client.save_assignments()

            QMessageBox.information(self, "Success", "Model configuration saved.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {str(e)}")