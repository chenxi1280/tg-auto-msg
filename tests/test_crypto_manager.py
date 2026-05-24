import unittest

from backend.utils.security.crypto import CryptoManager


class CryptoManagerTests(unittest.TestCase):
    def test_decrypt_uses_fallback_keys_for_existing_ciphertext(self):
        old_key = CryptoManager.generate_key()
        new_key = CryptoManager.generate_key()
        encrypted = CryptoManager(old_key).encrypt("telegram-session")

        manager = CryptoManager(new_key, fallback_encryption_keys=[old_key])

        self.assertEqual(manager.decrypt(encrypted), "telegram-session")

    def test_encrypt_always_uses_primary_key(self):
        old_key = CryptoManager.generate_key()
        new_key = CryptoManager.generate_key()
        manager = CryptoManager(new_key, fallback_encryption_keys=[old_key])

        encrypted = manager.encrypt("new-session")

        self.assertEqual(CryptoManager(new_key).decrypt(encrypted), "new-session")
        with self.assertRaises(ValueError):
            CryptoManager(old_key).decrypt(encrypted)


if __name__ == "__main__":
    unittest.main()
