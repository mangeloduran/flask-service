import os


class Config:
    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOTTO_TTL_HOURS = int(os.environ.get("LOTTO_TTL_HOURS", "24"))
