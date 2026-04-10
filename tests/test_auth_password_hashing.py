import unittest

from backend.h5_backend.services.auth.service import AuthService


class AuthPasswordHashingTests(unittest.TestCase):
    def test_new_password_hash_round_trips_without_passlib_format(self):
        service = AuthService()

        hashed = service.get_password_hash("Password123")

        self.assertTrue(hashed.startswith("pbkdf2_sha256$"))
        self.assertTrue(service.verify_password("Password123", hashed))
        self.assertFalse(service.verify_password("WrongPassword", hashed))

    def test_verify_password_accepts_legacy_passlib_pbkdf2_hash(self):
        service = AuthService()
        legacy_hash = "$pbkdf2-sha256$29000$pDRGaK21lpKSslZKCQGA0A$zkHyXR5F58rVt5JZpzseZDyZk035E4VF0xODPCjR7Fw"

        self.assertTrue(service.verify_password("Password123", legacy_hash))
        self.assertFalse(service.verify_password("WrongPassword", legacy_hash))

    def test_verify_password_accepts_legacy_bcrypt_hash(self):
        service = AuthService()
        legacy_hash = "$2b$12$kh5jeFvebGDT0RbeN81b5.XJct2xu3Y41ggXwYguqkTOxvQ6NN26u"

        self.assertTrue(service.verify_password("Password123", legacy_hash))
        self.assertFalse(service.verify_password("WrongPassword", legacy_hash))


if __name__ == "__main__":
    unittest.main()
