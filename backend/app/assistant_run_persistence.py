"""Shared atomic text writes and stable hashes for the two assistant journals."""
import hashlib
import json
from uuid import uuid4


def atomic_write_text(path, text):
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
