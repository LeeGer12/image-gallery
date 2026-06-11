import logging

from PySide6.QtCore import QObject, Signal
from sqlalchemy import select, update

from core.database import SessionLocal
from core.models import Album, Folder, Image, OperationLog, album_image_table

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
    conflict_images = Signal(list)  # 冲突的 image_id 列表

    def __init__(self, operation: str, user_id: int | None = None, **kwargs):
        super().__init__()
        self._operation = operation
        self._user_id = user_id
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

            # 记录操作日志
            if self._user_id:
                log = OperationLog(
                    user_id=self._user_id, action=self._operation,
                    target_desc=f"{self._operation}: {list(self._kwargs.keys())}"
                )
                db.add(log)
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
        album = Album(name=name, description=description, created_by=self._user_id)
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
        force = self._kwargs.get("force", False)
        expected_versions = self._kwargs.get("expected_versions", {})

        images = db.execute(
            select(Image).where(Image.id.in_(image_ids))
        ).scalars().all()

        if not force and expected_versions:
            conflicts = []
            for image in images:
                expected = expected_versions.get(image.id)
                if expected is not None and image.version != expected:
                    conflicts.append(image.id)
            if conflicts:
                self.conflict_images.emit(conflicts)
                return

        for image in images:
            if self._cancelled:
                break
            _set_field(image, "project_type", project_type, only_empty)
            _set_field(image, "style_name", style_name, only_empty)
            image.version += 1

    def _quick_classify(self, db):
        """快速分类：直接覆盖设置 project_type/style_name"""
        image_ids = self._kwargs["image_ids"]
        project_type = self._kwargs.get("project_type", "")
        style_name = self._kwargs.get("style_name", "")
        force = self._kwargs.get("force", False)
        expected_versions = self._kwargs.get("expected_versions", {})

        images = db.execute(
            select(Image).where(Image.id.in_(image_ids))
        ).scalars().all()

        if not force and expected_versions:
            conflicts = []
            for image in images:
                expected = expected_versions.get(image.id)
                if expected is not None and image.version != expected:
                    conflicts.append(image.id)
            if conflicts:
                self.conflict_images.emit(conflicts)
                return

        for image in images:
            if self._cancelled:
                break
            image.project_type = project_type
            image.style_name = style_name
            image.version += 1

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
