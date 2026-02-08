"""
加密工具类

使用 AES-256-GCM 加密算法对敏感数据进行加密存储。
用于加密：
- StringSession（Telegram 会话）
- 代理密码
"""
import os
import base64
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from loguru import logger


class CryptoManager:
    """
    加密管理器 - AES-256-GCM

    使用说明：
    1. 从环境变量获取加密密钥（32 字节）
    2. 每次加密生成随机 nonce（12 字节）
    3. 返回格式：base64(nonce + ciphertext)
    """

    # Nonce 长度（AES-GCM 推荐使用 12 字节）
    NONCE_LENGTH = 12

    # 密钥长度（AES-256 需要 32 字节）
    KEY_LENGTH = 32

    def __init__(self, encryption_key: str | None = None):
        """
        初始化加密管理器

        Args:
            encryption_key: Base64 编码的加密密钥（32 字节）
                           如果为 None，则从环境变量读取或生成新密钥
        """
        if encryption_key:
            # 从 Base64 解码密钥
            self._key = base64.b64decode(encryption_key.encode())
            if len(self._key) != self.KEY_LENGTH:
                raise ValueError(f"加密密钥必须是 {self.KEY_LENGTH} 字节")
        else:
            # 从环境变量读取或生成新密钥
            key_str = os.getenv("ENCRYPTION_KEY")
            if key_str:
                self._key = base64.b64decode(key_str.encode())
                if len(self._key) != self.KEY_LENGTH:
                    raise ValueError(f"ENCRYPTION_KEY 必须是 {self.KEY_LENGTH} 字节的 Base64 编码")
            else:
                # 生成新密钥（仅用于开发环境）
                logger.warning("未设置 ENCRYPTION_KEY 环境变量，使用临时密钥（仅限开发环境）")
                self._key = os.urandom(self.KEY_LENGTH)

        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> str:
        """
        加密文本

        Args:
            plaintext: 明文

        Returns:
            Base64 编码的密文（nonce + ciphertext）

        Raises:
            ValueError: 如果 plaintext 为空
        """
        if not plaintext:
            raise ValueError("明文不能为空")

        # 生成随机 nonce
        nonce = os.urandom(self.NONCE_LENGTH)

        # 加密
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

        # 返回 base64(nonce + ciphertext)
        result = nonce + ciphertext
        return base64.b64encode(result).decode('utf-8')

    def decrypt(self, encrypted_text: str) -> str:
        """
        解密文本

        Args:
            encrypted_text: Base64 编码的密文（nonce + ciphertext）

        Returns:
            明文

        Raises:
            ValueError: 如果解密失败或格式错误
        """
        if not encrypted_text:
            raise ValueError("密文不能为空")

        try:
            # Base64 解码
            data = base64.b64decode(encrypted_text.encode())

            # 分离 nonce 和 ciphertext
            nonce = data[:self.NONCE_LENGTH]
            ciphertext = data[self.NONCE_LENGTH:]

            # 解密
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode('utf-8')

        except Exception as e:
            logger.error(f"解密失败: {e}")
            raise ValueError(f"解密失败: {e}")

    def get_key_base64(self) -> str:
        """
        获取 Base64 编码的密钥

        Returns:
            Base64 编码的密钥字符串
        """
        return base64.b64encode(self._key).decode('utf-8')

    @staticmethod
    def generate_key() -> str:
        """
        生成新的加密密钥

        Returns:
            Base64 编码的密钥字符串
        """
        key = os.urandom(CryptoManager.KEY_LENGTH)
        return base64.b64encode(key).decode('utf-8')


# 全局单例
_crypto_manager: CryptoManager | None = None


def get_crypto_manager() -> CryptoManager:
    """
    获取全局加密管理器实例

    Returns:
        CryptoManager 实例
    """
    global _crypto_manager
    if _crypto_manager is None:
        _crypto_manager = CryptoManager()
    return _crypto_manager


def encrypt_string_session(session: str) -> str:
    """
    加密 StringSession

    Args:
        session: Telethon StringSession

    Returns:
        加密后的字符串
    """
    return get_crypto_manager().encrypt(session)


def decrypt_string_session(encrypted_session: str) -> str:
    """
    解密 StringSession

    Args:
        encrypted_session: 加密的 StringSession

    Returns:
        解密后的 StringSession
    """
    return get_crypto_manager().decrypt(encrypted_session)


def encrypt_proxy_password(password: str) -> str:
    """
    加密代理密码

    Args:
        password: 代理密码

    Returns:
        加密后的字符串
    """
    return get_crypto_manager().encrypt(password)


def decrypt_proxy_password(encrypted_password: str) -> str:
    """
    解密代理密码

    Args:
        encrypted_password: 加密的代理密码

    Returns:
        解密后的密码
    """
    return get_crypto_manager().decrypt(encrypted_password)


def generate_encryption_key() -> str:
    """
    生成新的加密密钥（用于初始化配置）

    Returns:
        Base64 编码的密钥字符串
    """
    return CryptoManager.generate_key()


def generate_bind_code() -> str:
    """
    生成 6 位数字绑定码

    Returns:
        6 位数字字符串（如 "882299"）
    """
    import random
    return f"{random.randint(100000, 999999)}"


def validate_bind_code(code: str) -> bool:
    """
    验证绑定码格式

    Args:
        code: 绑定码

    Returns:
        是否有效
    """
    return code.isdigit() and len(code) == 6
