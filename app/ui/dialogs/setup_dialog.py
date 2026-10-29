from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


class SetupDialog(QDialog):
    """First-launch dialog: keep the default data folder or pick a custom one."""

    def __init__(
        self,
        default_dir: Path,
        current_dir: Path | None = None,
        message: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Classroom Manager – Data folder")
        self.setMinimumWidth(520)
        self.default_dir = default_dir

        intro = QLabel(
            "<b>Where should Classroom Manager keep your data?</b><br>"
            "All classes, grades and attendance are stored in a single file on this "
            "computer. Nothing is sent over the internet. Automatic backups are kept "
            "in a <i>backups</i> folder next to it."
        )
        intro.setWordWrap(True)

        self.default_radio = QRadioButton("Use the default location")
        default_label = QLabel(str(default_dir))
        default_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        default_label.setContentsMargins(24, 0, 0, 0)

        self.custom_radio = QRadioButton("Use a custom folder (e.g. another drive)")
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("Choose a folder…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(24, 0, 0, 0)
        custom_row.addWidget(self.custom_edit, stretch=1)
        custom_row.addWidget(browse)

        group = QButtonGroup(self)
        group.addButton(self.default_radio)
        group.addButton(self.custom_radio)
        self.custom_radio.toggled.connect(self.custom_edit.setEnabled)
        self.custom_radio.toggled.connect(browse.setEnabled)

        if current_dir is not None and current_dir != default_dir:
            self.custom_radio.setChecked(True)
            self.custom_edit.setText(str(current_dir))
        else:
            self.default_radio.setChecked(True)
            self.custom_edit.setEnabled(False)
            browse.setEnabled(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Quit")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        if message:
            warning = QLabel(message)
            warning.setWordWrap(True)
            warning.setStyleSheet("font-weight: bold;")
            layout.addWidget(warning)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addWidget(self.default_radio)
        layout.addWidget(default_label)
        layout.addWidget(self.custom_radio)
        layout.addLayout(custom_row)
        layout.addStretch()
        layout.addWidget(buttons)

    def _browse(self) -> None:
        start = self.custom_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose data folder", start)
        if folder:
            self.custom_edit.setText(folder)

    def chosen_dir(self) -> Path:
        if self.default_radio.isChecked():
            return self.default_dir
        return Path(self.custom_edit.text().strip()).expanduser()

    def accept(self) -> None:
        if self.custom_radio.isChecked():
            text = self.custom_edit.text().strip()
            if not text or not Path(text).expanduser().is_absolute():
                QMessageBox.warning(self, "Data folder", "Please choose a full folder path.")
                return
        super().accept()
