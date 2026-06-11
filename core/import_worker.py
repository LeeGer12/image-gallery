import logging
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from config import STORAGE_ROOT
from core.database import SessionLocal
from core.models import Image, OperationLog

logger = logging.getLogger(__name__)


class ImportWorker(QObject):
    """后台执行导入操作：复制文件到 STORAGE_ROOT 并更新数据库。"""

    progress = Signal(int, int)  # current, total
    image_imported = Signal(int)  # image_id
    finished = Signal()
    error = Signal(str)

    def __init__(self, image_ids: list[int], project_name: str,
                 project_type: str, style_name: str, user_id: int | None = None):
        super().__init__()
        self._image_ids = image_ids
        self._project_name = project_name
        self._project_type = project_type
        self._style_name = style_name
        self._user_id = user_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        db = SessionLocal()
        try:
            total = len(self._image_ids)
            dest_dir = Path(STORAGE_ROOT) / self._project_name / self._project_type / self._style_name
            dest_dir.mkdir(parents=True, exist_ok=True)

            for idx, image_id in enumerate(self._image_ids):
                if self._cancelled:
                    break

                image = db.get(Image, image_id)
                if not image:
                    continue

                src = Path(image.file_path)
                if not src.exists() and image.storage_path:
                    src = Path(image.storage_path)
                if not src.exists():
                    continue

                dest_path = dest_dir / image.file_name

                if dest_path.exists() and dest_path.resolve() != src.resolve():
                    stem = dest_path.stem
                    suffix = dest_path.suffix
                    counter = 1
                    while dest_path.exists():
                        dest_path = dest_dir / f"{stem}_{counter}{suffix}"
                        counter += 1

                shutil.copy2(str(src), str(dest_path))

                image.imported = True
                image.project_name = self._project_name
                image.project_type = self._project_type
                image.style_name = self._style_name
                image.storage_path = str(dest_path)
                if self._user_id:
                    image.imported_by = self._user_id

                if (idx + 1) % 50 == 0:
                    db.commit()

                self.image_imported.emit(image_id)
                self.progress.emit(idx + 1, total)

            db.commit()

            # 记录操作日志
            if self._user_id:
                log = OperationLog(
                    user_id=self._user_id, action="import",
                    target_desc=f"导入 {total} 张图片到 {self._project_name}/{self._project_type}/{self._style_name}"
                )
                db.add(log)
                db.commit()

            self.finished.emit()
        except Exception as e:
            db.rollback()
            logger.error("ImportWorker 出错: %s", e)
            self.error.emit(str(e))
        finally:
            db.close()
