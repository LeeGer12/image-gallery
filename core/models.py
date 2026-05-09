from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# 图片-标签关联表
image_tag_table = Table(
    "image_tags",
    Base.metadata,
    Column("image_id", Integer, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

# 相册-图片关联表
album_image_table = Table(
    "album_images",
    Base.metadata,
    Column("album_id", Integer, ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True),
    Column("image_id", Integer, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True),
    Column("sort_order", Integer, default=0),
)


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    watched: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scan: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)

    # 关联
    images: Mapped[List["Image"]] = relationship("Image", back_populates="folder")


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    color_space: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    imported: Mapped[bool] = mapped_column(Boolean, default=False)
    project_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    project_type: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    style_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    thumb_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)
    flag: Mapped[int] = mapped_column(Integer, default=0)
    exif_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    folder_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("folders.id"), nullable=True
    )

    # 关联
    folder: Mapped[Optional["Folder"]] = relationship("Folder", back_populates="images")
    tags: Mapped[List["Tag"]] = relationship(
        "Tag", secondary=image_tag_table, back_populates="images"
    )
    albums: Mapped[List["Album"]] = relationship(
        "Album", secondary=album_image_table, back_populates="images"
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(7), default="#808080")
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # 关联
    images: Mapped[List["Image"]] = relationship(
        "Image", secondary=image_tag_table, back_populates="tags"
    )


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关联
    images: Mapped[List["Image"]] = relationship(
        "Image", secondary=album_image_table, back_populates="albums"
    )
