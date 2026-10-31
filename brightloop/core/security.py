"""
Core Security & Cryptography Engine.
Implements OWASP-recommended Scrypt password hashing with exact parameters,
hashed session tokens, cryptographically secure reset tokens, and CSRF protection.
"""

import re
import secrets
import hashlib
from typing import Tuple, Optional
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Exact Scrypt Hashing Parameters (OWASP Recommended)
SCRYPT_N = 16384       # CPU/memory cost parameter (2^14)
SCRYPT_R = 8           # Block size parameter
SCRYPT_P = 1           # Parallelization parameter
SCRYPT_KEY_LEN = 32    # Output derived key length in bytes
SCRYPT_SALT_LEN = 16   # Salt length in bytes

class SecurityError(Exception):
    pass

class PasswordComplexityError(SecurityError):
    pass

def validate_password_strength(password: str) -> None:
    """
    Validates spec requirements:
    - More than 8 characters (> 8)
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one special character
    """
    if len(password) <= 8:
        raise PasswordComplexityError("Password must be more than eight characters long.")
    if not re.search(r"[A-Z]", password):
        raise PasswordComplexityError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise PasswordComplexityError("Password must contain at least one lowercase letter.")
    if not re.search(r"[\W_]", password):
        raise PasswordComplexityError("Password must contain at least one special character.")

def hash_password(password: str, salt_bytes: Optional[bytes] = None) -> Tuple[str, str]:
    """
    Hashes password using Scrypt with exact parameters.
    Returns (hash_hex, salt_hex).
    """
    if salt_bytes is None:
        salt_bytes = secrets.token_bytes(SCRYPT_SALT_LEN)
    elif len(salt_bytes) != SCRYPT_SALT_LEN:
        raise ValueError(f"Salt must be {SCRYPT_SALT_LEN} bytes long.")

    kdf = Scrypt(
        salt=salt_bytes,
        length=SCRYPT_KEY_LEN,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P
    )
    derived_key = kdf.derive(password.encode("utf-8"))
    return derived_key.hex(), salt_bytes.hex()

def verify_password(password: str, stored_hash_hex: str, salt_hex: str) -> bool:
    """Verifies password using constant-time comparison."""
    salt_bytes = bytes.fromhex(salt_hex)
    stored_hash_bytes = bytes.fromhex(stored_hash_hex)
    kdf = Scrypt(
        salt=salt_bytes,
        length=SCRYPT_KEY_LEN,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P
    )
    try:
        kdf.verify(password.encode("utf-8"), stored_hash_bytes)
        return True
    except Exception:
        return False

def hash_token(raw_token: str) -> str:
    """Hashes token using SHA-256 for secure database storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def generate_session_credentials() -> Tuple[str, str, str]:
    """
    Generates a secure session.
    Returns (raw_session_token, token_hash_hex, csrf_token).
    The raw token is returned to the user in HTTP-only cookie; only the hash is stored in DB.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    csrf_token = secrets.token_urlsafe(32)
    return raw_token, token_hash, csrf_token

def generate_reset_token() -> Tuple[str, str]:
    """
    Generates password reset token.
    Returns (raw_reset_token, token_hash_hex).
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    return raw_token, token_hash