import os
from pathlib import Path

from core.settings import load_settings

APP_NAME = "ImageGallery"
APP_VERSION = "0.2.0"

# 优先从 settings.json 读取，fallback 到环境变量
_settings = load_settings()
_server_ip = _settings.get("server_ip")

if _server_ip:
    # 局域网模式：连接中枢电脑，账号密码写死
    DB_HOST = _server_ip
    DB_PORT = 5432
    DB_NAME = "imagegallery"
    DB_USER = "gallery"
    DB_PASSWORD = "ImageGallery2026"
    STORAGE_ROOT = Path(f"//{_server_ip}/ImageGalleryStorage")
else:
    # 本地开发模式：从环境变量读取
    DB_HOST = os.environ.get("IG_DB_HOST", "localhost")
    DB_PORT = int(os.environ.get("IG_DB_PORT", "5432"))
    DB_NAME = os.environ.get("IG_DB_NAME", "imagegallery")
    DB_USER = os.environ.get("IG_DB_USER", "gallery")
    DB_PASSWORD = os.environ.get("IG_DB_PASSWORD", "")
    STORAGE_ROOT = Path(os.environ.get("IG_STORAGE_ROOT", "G:/ImageGalleryStorage"))

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 缩略图缓存目录（各电脑本地缓存）
THUMB_CACHE_ROOT = Path.home() / ".image_gallery" / "thumbs"
THUMB_CACHE_MAX_GB = 2

# 缩略图尺寸
THUMB_SIZES = {
    "small": 128,
    "medium": 256,
    "large": 512,
}
DEFAULT_THUMB_SIZE = "medium"

# 分页
PAGE_SIZE = 200

# 扫描线程池大小
SCANNER_WORKERS = 4
