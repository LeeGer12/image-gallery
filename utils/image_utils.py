import json
import logging
from pathlib import Path

from PIL import Image, ExifTags

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif",
    ".heif", ".heic",
    ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".dng", ".raf",
}

_RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".dng", ".raf"}
_HEIF_EXTENSIONS = {".heif", ".heic"}


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _extract_exif(img: Image.Image) -> dict:
    """从 Pillow Image 提取 EXIF 信息，返回简化的字典"""
    exif_data = {}
    try:
        raw = img.getexif()
        if not raw:
            return exif_data
        for tag_id, value in raw.items():
            tag_name = ExifTags.TAGS.get(tag_id, tag_id)
            # 跳过复杂类型，只保留可序列化的值
            if isinstance(value, (str, int, float)):
                exif_data[str(tag_name)] = value
            elif isinstance(value, bytes):
                try:
                    exif_data[str(tag_name)] = value.decode("utf-8", errors="replace")
                except Exception:
                    pass
    except Exception:
        pass
    return exif_data


def read_image_info(path: Path) -> dict | None:
    """读取图片元数据，返回字典。失败返回 None。

    返回字段：
        width, height, format, color_space, exif_json
    """
    suffix = path.suffix.lower()

    try:
        if suffix in _RAW_EXTENSIONS:
            return _read_raw_info(path)
        elif suffix in _HEIF_EXTENSIONS:
            return _read_heif_info(path)
        else:
            return _read_pillow_info(path)
    except Exception as e:
        logger.warning("读取图片信息失败 %s: %s", path, e)
        return None


def _read_pillow_info(path: Path) -> dict:
    with Image.open(path) as img:
        width, height = img.size
        fmt = img.format or ""
        color_space = img.mode
        exif = _extract_exif(img)
    return {
        "width": width,
        "height": height,
        "format": fmt,
        "color_space": color_space,
        "exif_json": json.dumps(exif, ensure_ascii=False) if exif else None,
    }


def _read_raw_info(path: Path) -> dict:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        width = raw.sizes.width
        height = raw.sizes.height
    return {
        "width": width,
        "height": height,
        "format": "RAW",
        "color_space": "",
        "exif_json": None,
    }


def _read_heif_info(path: Path) -> dict:
    import pillow_heif

    heif_file = pillow_heif.open_heif(str(path), convert_hdr_to_8bit=False)
    width = heif_file.size[0]
    height = heif_file.size[1]
    # 尝试读取 EXIF
    exif = {}
    if heif_file.info.get("exif"):
        try:
            img = Image.open(path)
            exif = _extract_exif(img)
            img.close()
        except Exception:
            pass
    return {
        "width": width,
        "height": height,
        "format": "HEIF",
        "color_space": "",
        "exif_json": json.dumps(exif, ensure_ascii=False) if exif else None,
    }


def generate_thumbnail(src_path: Path, dst_path: Path, size: int) -> bool:
    """生成缩略图并保存。成功返回 True。"""
    suffix = src_path.suffix.lower()

    try:
        if suffix in _RAW_EXTENSIONS:
            img = _load_raw_as_pil(src_path)
        else:
            img = Image.open(src_path)
            img.load()  # 提前加载像素数据，尽早发现损坏文件

        # RGBA/P 模式转 RGB，避免 JPEG 保存报错
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(dst_path), "JPEG", quality=85)
        img.close()
        return True
    except Exception as e:
        logger.warning("生成缩略图失败 %s: %s", src_path, e)
        return False


def _load_raw_as_pil(path: Path) -> Image.Image:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess()
    return Image.fromarray(rgb)
