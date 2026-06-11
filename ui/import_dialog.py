from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
)

from config import STORAGE_ROOT
from ui.thread_utils import stop_thread


class ImportDialog(QDialog):
    """导入图片到库对话框。"""

    import_finished = Signal()

    def __init__(self, image_ids: list[int], parent=None, user_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("导入到库")
        self.setMinimumWidth(450)
        self._image_ids = image_ids
        self._user_id = user_id
        self._thread = None
        self._worker = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"已选择 {len(image_ids)} 张图片"))

        form = QFormLayout()
        self._project_input = QLineEdit()
        self._project_input.setPlaceholderText("请输入项目名称")
        self._project_input.textChanged.connect(self._update_preview)
        form.addRow("项目名称:", self._project_input)

        self._type_input = QLineEdit()
        self._type_input.setPlaceholderText("请输入项目类型（如售楼处、样板间）")
        self._type_input.textChanged.connect(self._update_preview)
        form.addRow("项目类型:", self._type_input)

        self._style_input = QLineEdit()
        self._style_input.setPlaceholderText("请输入风格名称")
        self._style_input.textChanged.connect(self._update_preview)
        form.addRow("风格名称:", self._style_input)

        layout.addLayout(form)

        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        layout.addWidget(self._preview_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel()
        layout.addWidget(self._status_label)

        self._button_box = QDialogButtonBox()
        self._btn_import = self._button_box.addButton(
            "开始导入", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._button_box.addButton(
            QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self._start_import)
        self._button_box.rejected.connect(self._on_cancel)
        layout.addWidget(self._button_box)

        self._update_preview()

    def _update_preview(self):
        project = self._project_input.text().strip()
        ptype = self._type_input.text().strip()
        style = self._style_input.text().strip()
        if project and ptype and style:
            dest = Path(STORAGE_ROOT) / project / ptype / style
            self._preview_label.setText(f"将复制到: {dest}/")
            self._btn_import.setEnabled(True)
        else:
            self._preview_label.setText("请输入项目名称、项目类型和风格名称")
            self._btn_import.setEnabled(False)

    def _start_import(self):
        from core.import_worker import ImportWorker

        project = self._project_input.text().strip()
        ptype = self._type_input.text().strip()
        style = self._style_input.text().strip()

        self._project_input.setEnabled(False)
        self._type_input.setEnabled(False)
        self._style_input.setEnabled(False)
        self._btn_import.setEnabled(False)

        self._progress_bar.setMaximum(len(self._image_ids))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._thread = QThread()
        self._worker = ImportWorker(self._image_ids, project, ptype, style, user_id=self._user_id)
        self._worker.moveToThread(self._thread)

        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _on_progress(self, current: int, total: int):
        self._progress_bar.setValue(current)
        self._status_label.setText(f"导入中: {current}/{total}")

    def _on_finished(self):
        self._status_label.setText("导入完成")
        self._cleanup_thread()
        self.import_finished.emit()

    def _on_error(self, msg: str):
        self._status_label.setText(f"导入失败: {msg}")
        self._cleanup_thread()
        self._project_input.setEnabled(True)
        self._type_input.setEnabled(True)
        self._style_input.setEnabled(True)
        self._btn_import.setEnabled(True)

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
        stop_thread(self._thread)
        self.reject()

    def _cleanup_thread(self):
        stop_thread(self._thread)
        self._thread = None
        self._worker = None
