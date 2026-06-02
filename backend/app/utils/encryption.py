from cryptography.fernet import Fernet
from app.core.config import config


def _get_fernet() -> Fernet:
    key = config.fernet_key.get_secret_value()
    if not key:
        raise RuntimeError("FERNET_KEY is not configured")
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """加密明文字符串，返回 base64 编码的密文。"""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """解密密文字符串，返回明文。"""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
