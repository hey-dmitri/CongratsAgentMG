import os
from pathlib import Path
from dotenv import load_dotenv

# Always load .env from the project root regardless of working directory
load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Serper.dev web search (for handle finding)
    SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

    # Upload
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
