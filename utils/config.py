"""Central application configuration, loaded once from environment variables.
Follows the EduJunction configuration pattern.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

# Load .env from backend directory or project root
load_dotenv(BASE_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    APP_NAME: str = os.getenv("APP_NAME", "TallyPilot")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")

    # Database
    _raw_db_url = os.getenv("DATABASE_URL")
    if not _raw_db_url and os.getenv("DB_USER") and os.getenv("DB_PASSWORD"):
        import urllib.parse
        _user = os.getenv("DB_USER", "root")
        _pass = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
        _host = os.getenv("DB_HOST", "localhost")
        _port = os.getenv("DB_PORT", "3306")
        _name = os.getenv("DB_NAME", "TallyPilot")
        DATABASE_URL: str = f"mysql+pymysql://{_user}:{_pass}@{_host}:{_port}/{_name}?charset=utf8mb4"
    else:
        DATABASE_URL: str = _raw_db_url or "mysql+pymysql://root:root@localhost:3306/TallyPilot?charset=utf8mb4"

    # Tally Prime XML HTTP Configuration
    TALLY_URL: str = os.getenv("TALLY_URL", "http://localhost:9000")
    TALLY_TIMEOUT: int = int(os.getenv("TALLY_TIMEOUT", "10"))
    TALLY_COMPANY_NAME: str = os.getenv("TALLY_COMPANY_NAME", "Demo Company (FY 2026-27)")
    TALLY_SIMULATION_MODE: bool = os.getenv("TALLY_SIMULATION_MODE", "True").lower() in ("true", "1", "yes")

    # Local Ollama / Categorizer
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")
    AI_CONFIDENCE_THRESHOLD: float = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.80"))

    # Folder Ingestion Paths
    INPUT_DIR: str = os.getenv("INPUT_DIR", str(PROJECT_ROOT / "input"))
    PROCESSED_DIR: str = os.getenv("PROCESSED_DIR", str(PROJECT_ROOT / "input" / "processed"))
    ERROR_DIR: str = os.getenv("ERROR_DIR", str(PROJECT_ROOT / "input" / "error"))

    # Security & CORS
    CORS_ORIGINS: list = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(",")
        if o.strip()
    ]
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()

