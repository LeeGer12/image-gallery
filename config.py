from pathlib import Path

APP_NAME = "ImageGallery"
APP_VERSION = "0.1.0"

# 数据存储根目录（导入模式使用，建议放在共享服务器）
STORAGE_ROOT = Path("G:/ImageGalleryStorage")

# 缩略图缓存目录（可本地或共享）
THUMB_CACHE_ROOT = Path.home() / ".image_gallery" / "thumbs"
THUMB_CACHE_MAX_GB = 2

# 缩略图尺寸
THUMB_SIZES = {
    "small": 128,
    "medium": 256,
    "large": 512,
}
DEFAULT_THUMB_SIZE = "medium"

# 数据库配置（从环境变量读取，fallback 到默认值）
import os

DB_HOST = os.environ.get("IG_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("IG_DB_PORT", "5432"))
DB_NAME = os.environ.get("IG_DB_NAME", "imagegallery")
DB_USER = os.environ.get("IG_DB_USER", "gallery")
DB_PASSWORD = os.environ.get("IG_DB_PASSWORD", "gallery123")

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 分页
PAGE_SIZE = 200

# 扫描线程池大小
SCANNER_WORKERS = 4
