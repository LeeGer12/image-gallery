import logging

from PySide6.QtCore import QObject, Signal
from sqlalchemy import select, update

from core.database import SessionLocal
from core.models import Album, Folder, Image, album_image_table

logger = logging.getLogger(__name__)


def _set_field(image, field: str, value: str, only_empty: bool):
    if not value:
        return
    if only_empty and getattr(image, field, None):
        return
    setattr(image, field, value)


class AlbumWorker(QObject):
    """后台执行相册 CRUD 和图片-相册关联操作。"""

    finished = Signal()
    error = Signal(str)
    album_created = Signal(int)
    albums_changed = Signal()

    def __init__(self, operation: str, **kwargs):
        super().__init__()
        self._operation = operation
        self._kwargs = kwargs
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        db = SessionLocal()
        try:
            if self._operation == "create":
                self._create(db)
            elif self._operation == "delete":
                self._delete(db)
            elif self._operation == "add_images":
                self._add_images(db)
            elif self._operation == "remove_images":
                self._remove_images(db)
            elif self._operation == "update_metadata":
                self._update_metadata(db)
            elif self._operation == "quick_classify":
                self._quick_classify(db)
            elif self._operation == "delete_folder":
                self._delete_folder(db)
            db.commit()
            self.albums_changed.emit()
            self.finished.emit()
        except Exception as e:
            db.rollback()
            logger.error("AlbumWorker 出错: %s", e)
            self.error.emit(str(e))
        finally:
            db.close()

    def _create(self, db):
        name = self._kwargs["name"]
        description = self._kwargs.get("description", "")
        album = Album(name=name, description=description)
        db.add(album)
        db.flush()
        album_id = album.id

        image_ids = self._kwargs.get("image_ids")
        if image_ids:
            self._batch_add_to_album(db, album_id, image_ids)

        self.album_created.emit(album_id)

    def _delete(self, db):
        album_id = self._kwargs["album_id"]
        album = db.get(Album, album_id)
        if album:
            db.delete(album)

    def _add_images(self, db):
        album_id = self._kwargs["album_id"]
        image_ids = self._kwargs["image_ids"]
        self._batch_add_to_album(db, album_id, image_ids)

    def _remove_images(self, db):
        album_id = self._kwargs["album_id"]
        image_ids = self._kwargs["image_ids"]
        db.execute(
            album_image_table.delete().where(
                album_image_table.c.album_id == album_id,
                album_image_table.c.image_id.in_(image_ids),
            )
        )

    def _update_metadata(self, db):
        image_ids = self._kwargs["image_ids"]
        project_type = self._kwargs.get("project_type", "")
        style_name = self._kwargs.get("style_name", "")
        only_empty = self._kwargs.get("only_empty", True)

        images = db.execute(
            select(Image).where(Image.id.in_(image_ids))
        ).scalars().all()
        for image in images:
            if self._cancelled:
                break
            _set_field(image, "project_type", project_type, only_empty)
            _set_field(image, "style_name", style_name, only_empty)

    def _quick_classify(self, db):
        """快速分类：直接覆盖设置 project_type/style_name"""
        image_ids = self._kwargs["image_ids"]
        project_type = self._kwargs.get("project_type", "")
        style_name = self._kwargs.get("style_name", "")

        images = db.execute(
            select(Image).where(Image.id.in_(image_ids))
        ).scalars().all()
        for image in images:
            if self._cancelled:
                break
            image.project_type = project_type
            image.style_name = style_name

    def _delete_folder(self, db):
        """删除索引：已导入图片保留(folder_id=NULL)，未导入图片记录删除，Folder记录删除"""
        folder_id = self._kwargs["folder_id"]
        folder = db.get(Folder, folder_id)
        if not folder:
            raise ValueError("文件夹不存在")

        # 已导入图片：批量清除 folder_id（不加载到内存）
        db.execute(
            update(Image)
            .where(Image.folder_id == folder_id, Image.imported == True)
            .values(folder_id=None)
        )

        # 未导入图片：批量删除
        db.execute(
            Image.__table__.delete().where(
                Image.folder_id == folder_id,
                Image.imported == False,
            )
        )

        db.delete(folder)

    def _batch_add_to_album(self, db, album_id: int, image_ids: list[int]):
        """批量添加图片到相册，跳过已存在的关联。"""
        existing = set(
            row[0] for row in db.execute(
                select(album_image_table.c.image_id).where(
                    album_image_table.c.album_id == album_id,
                    album_image_table.c.image_id.in_(image_ids),
                )
            ).all()
        )
        new_ids = [img_id for img_id in image_ids if img_id not in existing]
        if new_ids:
            db.execute(
                album_image_table.insert(),
                [{"album_id": album_id, "image_id": img_id} for img_id in new_ids],
            )
