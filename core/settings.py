"""本地配置文件管理。存储服务器 IP 等连接信息。"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_DIR = Path.home() / ".image_gallery"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"


def load_settings() -> dict:
    """读取 settings.json，不存在或解析失败则返回空 dict。"""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 settings.json 失败: %s", e)
        return {}


def save_settings(data: dict):
    """写入 settings.json，自动创建目录。"""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("配置已保存到 %s", SETTINGS_PATH)


def get_server_ip() -> str | None:
    """返回已保存的服务器 IP，未配置返回 None。"""
    return load_settings().get("server_ip")
