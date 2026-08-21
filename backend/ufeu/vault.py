"""Encrypted local storage for marketplace credentials and sessions.

Deliverable (b) in practice. What lands here is one of three things:

  api_key   real API credentials you were issued (eBay, Tradera) — the clean case;
  session   cookies or a bearer token you exported from your own logged-in
            browser, for sites with no API;
  none      nothing needed.

Nothing is ever transmitted anywhere except back to the marketplace it belongs
to. The file is Fernet-encrypted with a key held at 0600 in the state dir, or
derived from ``UFEU_VAULT_PASSPHRASE`` if you set one (better: the key file
alone is only as safe as the account running the app).
"""

from __future__ import annotations

import base64
import json
import os
import stat
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .settings import state_dir

_VAULT_FILE = "vault.enc"
_KEY_FILE = "vault.key"
_SALT_FILE = "vault.salt"


class VaultError(RuntimeError):
    pass


def _fernet() -> Fernet:
    passphrase = os.environ.get("UFEU_VAULT_PASSPHRASE")
    if passphrase:
        salt_path = state_dir() / _SALT_FILE
        if not salt_path.exists():
            salt_path.write_bytes(os.urandom(16))
            salt_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        kdf = Scrypt(salt=salt_path.read_bytes(), length=32, n=2**14, r=8, p=1)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8"))))

    key_path = state_dir() / _KEY_FILE
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return Fernet(key_path.read_bytes())


def _read_all() -> dict[str, dict[str, Any]]:
    path = state_dir() / _VAULT_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(path.read_bytes()).decode("utf-8"))
    except InvalidToken as exc:
        raise VaultError(
            "Vault could not be decrypted. Wrong UFEU_VAULT_PASSPHRASE, or the "
            f"key file at {state_dir() / _KEY_FILE} no longer matches {path}."
        ) from exc


def _write_all(data: dict[str, dict[str, Any]]) -> None:
    path = state_dir() / _VAULT_FILE
    path.write_bytes(_fernet().encrypt(json.dumps(data, indent=2).encode("utf-8")))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def set_credentials(marketplace_id: str, **fields: Any) -> None:
    """Store (or merge into) the credentials for one marketplace."""
    data = _read_all()
    entry = data.get(marketplace_id, {})
    entry.update({k: v for k, v in fields.items() if v is not None})
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    data[marketplace_id] = entry
    _write_all(data)


def get_credentials(marketplace_id: str) -> dict[str, Any]:
    return _read_all().get(marketplace_id, {})


def delete_credentials(marketplace_id: str) -> bool:
    data = _read_all()
    if marketplace_id not in data:
        return False
    del data[marketplace_id]
    _write_all(data)
    return True


def status() -> dict[str, dict[str, Any]]:
    """Non-secret summary for the UI: which sites are configured, and how.

    Never returns the secrets themselves — only field names and timestamps.
    """
    out: dict[str, dict[str, Any]] = {}
    for market_id, entry in _read_all().items():
        out[market_id] = {
            "fields": sorted(k for k in entry if k != "updated_at"),
            "updated_at": entry.get("updated_at"),
        }
    return out
