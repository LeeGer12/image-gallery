"""密码哈希与验证工具。使用 PBKDF2-SHA256，纯标准库实现。"""

import hashlib
import os


def hash_password(password: str) -> str:
    """将明文密码转为 'salt_hex:hash_hex' 格式的哈希字符串。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha-256", password.encode(), salt, 100000)
    return salt.hex() + ":" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    """验证明文密码是否匹配存储的哈希。"""
    salt_hex, hash_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha-256", password.encode(), salt, 100000)
    return dk.hex() == hash_hex
