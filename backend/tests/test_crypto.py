import os
import time

import pytest

from rushd.security.crypto import (
    CryptoError,
    KeyRing,
    generate_master_key_file,
    load_master_key,
)


@pytest.fixture
def kr():
    return KeyRing(os.urandom(32))


def test_blob_roundtrip_and_fresh_nonce(kr):
    a = kr.encrypt_blob(b"secret image", "image:abc")
    b = kr.encrypt_blob(b"secret image", "image:abc")
    assert a != b  # random nonce: equal plaintexts do not produce equal ciphertexts
    assert kr.decrypt_blob(a, "image:abc") == b"secret image"


def test_tampering_is_detected(kr):
    token = bytearray(kr.encrypt_blob(b"patient data", "image:abc"))
    token[-1] ^= 1
    with pytest.raises(CryptoError):
        kr.decrypt_blob(bytes(token), "image:abc")


def test_ciphertext_is_bound_to_its_record(kr):
    token = kr.encrypt_json({"name": "x"}, "ai:record-1")
    with pytest.raises(CryptoError):
        kr.decrypt_json(token, "ai:record-2")  # swapping records between rows fails


def test_wrong_key_fails(kr):
    other = KeyRing(os.urandom(32))
    with pytest.raises(CryptoError):
        other.decrypt_blob(kr.encrypt_blob(b"x", "a"), "a")


def test_domain_separation(kr):
    token = kr.encrypt_field(b"x", "a")
    with pytest.raises(CryptoError):
        kr.decrypt_blob(token, "a")  # field key and blob key are different


def test_signed_tokens(kr):
    token = kr.sign_token({"uid": 5}, ttl_seconds=60)
    assert kr.verify_token(token)["uid"] == 5
    assert kr.verify_token(token[:-2] + "AA") is None
    assert KeyRing(os.urandom(32)).verify_token(token) is None
    expired = kr.sign_token({"uid": 5}, ttl_seconds=-1)
    time.sleep(0.01)
    assert kr.verify_token(expired) is None


def test_master_key_file_permissions(tmp_path):
    path = tmp_path / "secrets" / "master.key"
    key = generate_master_key_file(path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert load_master_key(path) == key
    os.chmod(path, 0o644)
    with pytest.raises(CryptoError):
        load_master_key(path)  # refuses a world-readable key
    with pytest.raises(FileExistsError):
        generate_master_key_file(path)  # never silently overwrite a key


def test_missing_key_message(tmp_path):
    with pytest.raises(CryptoError, match="init"):
        load_master_key(tmp_path / "nope.key")
