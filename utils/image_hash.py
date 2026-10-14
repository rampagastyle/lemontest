"""Хеширование изображений для дедупликации."""
import hashlib
from io import BytesIO


def get_image_hash(image_bytes: bytes) -> str:
    """Возвращает SHA256 хеш изображения."""
    return hashlib.sha256(image_bytes).hexdigest()
