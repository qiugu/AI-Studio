import os
import pytest
from cryptography.fernet import Fernet

# 测试用 key（不依赖 .env）
TEST_KEY = Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("FERNET_KEY", TEST_KEY)
    from cryptography.fernet import Fernet as F
    f = F(TEST_KEY.encode())
    plaintext = "sk-test-api-key-12345"
    encrypted = f.encrypt(plaintext.encode()).decode()
    decrypted = f.decrypt(encrypted.encode()).decode()
    assert decrypted == plaintext


def test_encrypt_produces_different_output_each_time():
    from cryptography.fernet import Fernet as F
    f = F(Fernet.generate_key())
    plaintext = "same-input"
    enc1 = f.encrypt(plaintext.encode())
    enc2 = f.encrypt(plaintext.encode())
    assert enc1 != enc2


def test_decrypt_wrong_key_raises():
    from cryptography.fernet import Fernet as F, InvalidToken
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()
    encrypted = F(key1).encrypt(b"secret")
    with pytest.raises(InvalidToken):
        F(key2).decrypt(encrypted)


def test_app_encrypt_decrypt(monkeypatch):
    """集成测试：通过 app.utils.encryption 加解密"""
    from pydantic import SecretStr
    import app.core.config as cfg_module
    cfg_module.config.fernet_key = SecretStr(TEST_KEY)

    import importlib
    import app.utils.encryption as enc_module
    importlib.reload(enc_module)

    plaintext = "my-secret-api-key"
    encrypted = enc_module.encrypt(plaintext)
    assert encrypted != plaintext
    assert enc_module.decrypt(encrypted) == plaintext

    # 恢复原始 key（从 .env 加载的实际 key）
    cfg_module.config = cfg_module.Config()
