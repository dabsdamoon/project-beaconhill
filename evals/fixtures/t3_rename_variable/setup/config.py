MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30


def get_config():
    return {
        "max_retries": MAX_RETRIES,
        "timeout": DEFAULT_TIMEOUT,
    }


def validate_config(cfg):
    if cfg["max_retries"] > MAX_RETRIES:
        raise ValueError("Too many retries")
    if cfg["timeout"] > DEFAULT_TIMEOUT * 2:
        raise ValueError("Timeout too large")
