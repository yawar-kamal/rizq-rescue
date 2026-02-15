from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    soniox_api_key: str
    gemini_api_key: str
    elevenlabs_api_key: str = ""  # Optional — only needed if using ElevenLabs TTS

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()

