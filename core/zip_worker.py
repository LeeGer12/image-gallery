import logging
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.database import SessionLocal
from core.models import Image

logger = logging.getLogger(__name__)


class ZipWorker(QObject):
    """后台打包选中图片为 zip 文件。"""

    progress = Signal(int, int)  # current, total
    finished = Signal(str)  # zip 文件路径
    error = Signal(str)

    def __init__(self, image_ids: list[int], output_path: str):
        super().__init__()
        self._image_ids = image_ids
        self._output_path = output_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        db = SessionLocal()
        try:
            with zipfile.ZipFile(self._output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                total = len(self._image_ids)
                for idx, img_id in enumerate(self._image_ids):
                    if self._cancelled:
                        break

                    image = db.get(Image, img_id)
                    if not image:
                        continue

                    # 确定源文件路径
                    src = Path(image.file_path)
                    if not src.exists() and image.storage_path:
                        src = Path(image.storage_path)
                    if not src.exists():
                        continue

                    # 构建 zip 内路径：分类目录/文件名
                    parts = []
                    if image.project_type:
                        parts.append(image.project_type)
                    if image.style_name:
                        parts.append(image.style_name)
                    if not parts:
                        parts.append("未分类")
                    arcname = "/".join(parts) + "/" + image.file_name

                    zf.write(str(src), arcname)
                    self.progress.emit(idx + 1, total)

            self.finished.emit(self._output_path)
        except Exception as e:
            logger.error("ZipWorker error: %s", e)
            self.error.emit(str(e))
        finally:
            db.close()
