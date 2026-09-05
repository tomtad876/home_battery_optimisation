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
    """Decrypt a Fernet token string back to a provider_config dict.

    Raises ValueError if the token is Fernet-encrypted but cannot be decrypted
    (e.g. PROVIDER_CONFIG_ENCRYPTION_KEY changed since the credentials were
    saved). Legacy unencrypted JSON is returned as-is.
    """
    import json
    if not token or token == "{}":
        return {}
    if is_encrypted(token):
        try:
            plaintext = _get_fernet().decrypt(token.encode() if isinstance(token, str) else token)
            return json.loads(plaintext)
        except Exception as exc:
            raise ValueError(
                "Cannot decrypt stored API credentials — the server's "
                "PROVIDER_CONFIG_ENCRYPTION_KEY does not match the key used "
                "when they were saved. Re-save credentials in Settings, or "
                "fix the server encryption key."
            ) from exc
    # Legacy unencrypted JSON — return as-is
    try:
        return json.loads(token)
    except Exception:
        return {}


def is_encrypted(token: str) -> bool:
    """Check if a string looks like a Fernet token (starts with 'gAAAAA')."""
    return isinstance(token, str) and token.startswith("gAAAAA")
