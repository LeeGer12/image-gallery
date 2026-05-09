import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from sqlalchemy.orm import Session

from config import THUMB_CACHE_ROOT, THUMB_SIZES
from core.database import SessionLocal
from core.models import Image
from utils.image_utils import generate_thumbnail

logger = logging.getLogger(__name__)


class ThumbnailWorker(QObject):
    """后台生成缩略图。放入 QThread 使用。"""

    thumbnail_ready = Signal(int, str)  # image_id, thumb_path
    finished = Signal()
    error = Signal(str)

    def __init__(self, image_ids: list[int], size_key: str = "medium"):
        super().__init__()
        self.image_ids = image_ids
        self.size = THUMB_SIZES.get(size_key, THUMB_SIZES["medium"])
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        db: Session = SessionLocal()
        try:
            for image_id in self.image_ids:
                if self._cancelled:
                    break

                image = db.get(Image, image_id)
                if not image:
                    continue

                # 已有缩略图则跳过
                if image.thumb_path and Path(image.thumb_path).exists():
                    self.thumbnail_ready.emit(image_id, image.thumb_path)
                    continue

                src = Path(image.file_path)
                if not src.exists() and image.storage_path:
                    src = Path(image.storage_path)
                if not src.exists():
                    continue

                dst = THUMB_CACHE_ROOT / f"{image_id}_{self.size}.jpg"
                if generate_thumbnail(src, dst, self.size):
                    image.thumb_path = str(dst)
                    db.commit()
                    self.thumbnail_ready.emit(image_id, str(dst))
                else:
                    db.rollback()

            self.finished.emit()
        except Exception as e:
            db.rollback()
            logger.error("缩略图生成出错: %s", e)
            self.error.emit(str(e))
        finally:
            db.close()
