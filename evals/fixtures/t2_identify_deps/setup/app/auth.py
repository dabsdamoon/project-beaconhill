import hashlib
import hmac


def validate_token(token: str) -> bool:
    return len(token) > 0
