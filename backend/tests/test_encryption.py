from cryptography.fernet import Fernet, InvalidToken
import pytest

# 测试用 key（不依赖 .env）
TEST_KEY = Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip(monkeypatch):
    """通过 app.utils.encryption 加解密往返测试"""
    from pydantic import SecretStr
    import app.core.config as cfg_module
    monkeypatch.setattr(cfg_module.config, "fernet_key", SecretStr(TEST_KEY))

    from app.utils.encryption import encrypt, decrypt
    plaintext = "sk-test-api-key-12345"
    encrypted = encrypt(plaintext)
    assert encrypted != plaintext
    assert decrypt(encrypted) == plaintext


def test_encrypt_produces_different_output_each_time(monkeypatch):
    """每次加密结果不同（Fernet 含随机 IV）"""
    from pydantic import SecretStr
    import app.core.config as cfg_module
    monkeypatch.setattr(cfg_module.config, "fernet_key", SecretStr(TEST_KEY))

    from app.utils.encryption import encrypt
    enc1 = encrypt("same-input")
    enc2 = encrypt("same-input")
    assert enc1 != enc2


def test_decrypt_wrong_key_raises(monkeypatch):
    """用错误 key 解密应抛出 InvalidToken"""
    wrong_key = Fernet.generate_key().decode()
    from pydantic import SecretStr
    import app.core.config as cfg_module

    # 用 TEST_KEY 加密
    monkeypatch.setattr(cfg_module.config, "fernet_key", SecretStr(TEST_KEY))
    from app.utils.encryption import encrypt
    ciphertext = encrypt("secret")

    # 用 wrong_key 解密 — 应抛出 InvalidToken
    monkeypatch.setattr(cfg_module.config, "fernet_key", SecretStr(wrong_key))
    from app.utils.encryption import decrypt
    with pytest.raises(InvalidToken):
        decrypt(ciphertext)


def test_empty_key_raises_runtime_error(monkeypatch):
    """未配置 key 时应抛出 RuntimeError"""
    from pydantic import SecretStr
    import app.core.config as cfg_module
    monkeypatch.setattr(cfg_module.config, "fernet_key", SecretStr(""))

    from app.utils.encryption import encrypt
    with pytest.raises(RuntimeError, match="FERNET_KEY is not configured"):
        encrypt("anything")
