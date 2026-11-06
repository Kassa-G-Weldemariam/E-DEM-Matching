from argon2 import PasswordHasher

from app.core.security import hash_password, verify_and_upgrade, verify_password


def test_hash_is_not_the_password_and_uses_argon2():
    hashed = hash_password("S3cure-password")
    assert hashed != "S3cure-password"
    assert hashed.startswith("$argon2")


def test_same_password_gives_different_hashes():
    # Each hash gets its own random salt.
    assert hash_password("same-password") != hash_password("same-password")


def test_correct_password_verifies():
    assert verify_password("S3cure-password", hash_password("S3cure-password")) is True


def test_wrong_password_fails():
    assert verify_password("wrong-password", hash_password("S3cure-password")) is False


def test_password_is_case_sensitive():
    assert verify_password("s3cure-password", hash_password("S3cure-password")) is False


def test_non_latin_passwords_work():
    amharic = "የይለፍ ቃል-123"
    assert verify_password(amharic, hash_password(amharic)) is True


def test_garbage_hash_returns_false_instead_of_crashing():
    assert verify_password("anything", "not-a-real-hash") is False


def test_fresh_hash_is_valid_and_needs_no_upgrade():
    valid, new_hash = verify_and_upgrade("S3cure-password", hash_password("S3cure-password"))
    assert valid is True
    assert new_hash is None


def test_wrong_password_never_returns_an_upgraded_hash():
    valid, new_hash = verify_and_upgrade("wrong-password", hash_password("S3cure-password"))
    assert valid is False
    assert new_hash is None


def test_garbage_hash_in_verify_and_upgrade_returns_false():
    assert verify_and_upgrade("anything", "not-a-real-hash") == (False, None)


def test_weak_old_hash_is_upgraded_after_a_correct_password():
    # A hash made with deliberately weak settings, like one saved by an older version of the app.
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("S3cure-password")

    valid, new_hash = verify_and_upgrade("S3cure-password", weak_hash)

    assert valid is True
    assert new_hash is not None and new_hash != weak_hash
    assert verify_password("S3cure-password", new_hash) is True