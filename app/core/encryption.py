import os
from cryptography.fernet import Fernet

_fernet = None

def _get_fernet():
    """Lazy-init Fernet with the key from environment."""
    global _fernet
    if _fernet is None:
        key = os.environ.get("PROVIDER_CONFIG_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "PROVIDER_CONFIG_ENCRYPTION_KEY not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_provider_config(config: dict) -> str:
    """Encrypt a provider_config dict and return a Fernet token string."""
    import json
    if not config:
        return "{}"
    plaintext = json.dumps(config).encode()
    token = _get_fernet().encrypt(plaintext)
    return token.decode()


def decrypt_provider_config(token: str) -> dict:
    """Decrypt a Fernet token string back to a provider_config dict."""
    import json
    if not token or token == "{}":
        return {}
    try:
        plaintext = _get_fernet().decrypt(token.encode() if isinstance(token, str) else token)
        return json.loads(plaintext)
    except Exception:
        # If decryption fails, it might be unencrypted legacy data — return as-is
        try:
            return json.loads(token)
        except Exception:
            return {}


def is_encrypted(token: str) -> bool:
    """Check if a string looks like a Fernet token (starts with 'gAAAAA')."""
    return isinstance(token, str) and token.startswith("gAAAAA")
