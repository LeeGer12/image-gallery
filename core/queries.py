from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Image


def get_distinct_classifications(db: Session) -> list[tuple[str, str | None]]:
    """返回所有 (project_type, style_name) 的去重组合。"""
    return db.execute(
        select(Image.project_type, Image.style_name)
        .where(Image.project_type.isnot(None), Image.project_type != "")
        .distinct()
    ).all()


def parse_classify_key(data: str) -> tuple[str, str]:
    """从 'ptype:xxx' 或 'style:xxx|yyy' 解析出 (project_type, style_name)。"""
    _, _, value = data.partition(":")
    parts = value.split("|")
    return (
        parts[0] if len(parts) > 0 else "",
        parts[1] if len(parts) > 1 else "",
    )


def format_classify_label(ptype: str = "", style: str = "") -> str:
    """格式化分类标签：'项目类型 / 风格'"""
    parts = [p for p in (ptype, style) if p]
    return " / ".join(parts)
