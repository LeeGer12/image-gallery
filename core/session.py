"""进程级用户会话管理。登录时写入，退出时清除。"""

_current_user: dict | None = None


def set_current_user(user_id: int, username: str, role: str, display_name: str = ""):
    global _current_user
    _current_user = {"id": user_id, "username": username, "role": role, "display_name": display_name}


def get_current_user() -> dict | None:
    return _current_user


def get_current_user_id() -> int | None:
    return _current_user["id"] if _current_user else None


def get_current_username() -> str | None:
    return _current_user["username"] if _current_user else None


def is_admin() -> bool:
    return _current_user is not None and _current_user["role"] == "admin"


def clear_session():
    global _current_user
    _current_user = None
