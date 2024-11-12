from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MEDIA_FOLDER: Path = Path("tweets_media")
    MAX_IMAGE_SIZE: int = 500
    IMAGE_QUALITY: int = 60
    TIMEOUT: int = 1200
    TIMEZONE: str = "US/Eastern"
    BLUESKY_LOGIN: str
    BLUESKY_PASSWORD: str

    class Config:
        env_file = ".env"


class BlueSkyError(Exception):
    """Base exception for BlueSky related errors"""

    pass


class AuthenticationError(BlueSkyError):
    """Raised when authentication fails"""

    pass


class MediaProcessingError(BlueSkyError):
    """Raised when media processing fails"""

    pass

class PostingError(BlueSkyError):
    """Raised when posting content fails"""

    pass