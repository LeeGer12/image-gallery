import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Folder, Image
from core.database import SessionLocal
from utils.image_utils import is_supported_image, read_image_info

logger = logging.getLogger(__name__)


class ScanWorker(QObject):
    """后台扫描文件夹，将图片信息写入数据库。放入 QThread 使用。"""

    progress = Signal(int, int)  # current, total
    image_scanned = Signal(int)  # image_id
    finished = Signal()
    error = Signal(str)

    def __init__(self, folder_id: int):
        super().__init__()
        self.folder_id = folder_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        db: Session = SessionLocal()
        try:
            folder = db.get(Folder, self.folder_id)
            if not folder:
                self.error.emit(f"文件夹 ID {self.folder_id} 不存在")
                return

            folder_path = Path(folder.path)
            if not folder_path.is_dir():
                self.error.emit(f"路径不存在: {folder.path}")
                return

            # 收集所有支持格式的文件
            files = [
                p for p in folder_path.rglob("*")
                if p.is_file() and is_supported_image(p)
            ]
            total = len(files)

            # 查询已存在的 file_path，避免重复
            existing = set(
                db.execute(
                    select(Image.file_path).where(Image.folder_id == self.folder_id)
                ).scalars()
            )

            count = 0
            for idx, file_path in enumerate(files):
                if self._cancelled:
                    break

                path_str = str(file_path)
                if path_str in existing:
                    continue

                info = read_image_info(file_path)
                if info is None:
                    continue

                stat = file_path.stat()
                image = Image(
                    file_path=path_str,
                    file_name=file_path.name,
                    file_size=stat.st_size,
                    width=info["width"],
                    height=info["height"],
                    format=info["format"],
                    color_space=info["color_space"],
                    created_at=datetime.fromtimestamp(stat.st_ctime),
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    exif_json=info["exif_json"],
                    folder_id=self.folder_id,
                )
                db.add(image)
                db.flush()
                count += 1
                self.image_scanned.emit(image.id)
                self.progress.emit(idx + 1, total)

            # 更新文件夹扫描信息
            folder.last_scan = datetime.utcnow()
            folder.file_count = db.query(Image).filter(
                Image.folder_id == self.folder_id
            ).count()
            db.commit()

            logger.info("扫描完成: %s, 新增 %d 张图片", folder.path, count)
            self.finished.emit()

        except Exception as e:
            db.rollback()
            logger.error("扫描出错: %s", e)
            self.error.emit(str(e))
        finally:
            db.close()
