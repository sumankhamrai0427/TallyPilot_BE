"""Central application configuration, loaded once from environment variables.
Follows the EduJunction configuration pattern.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure stdout and stderr handle UTF-8 cleanly on Windows without UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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
    if _raw_db_url:
        DATABASE_URL: str = _raw_db_url
    else:
        import urllib.parse
        _user = os.getenv("DB_USER", "root")
        _pass = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
        _host = os.getenv("DB_HOST", "localhost")
        _port = os.getenv("DB_PORT", "3306")
        _name = os.getenv("DB_NAME", "TallyPilot_V2")
        if _pass:
            DATABASE_URL: str = f"mysql+pymysql://{_user}:{_pass}@{_host}:{_port}/{_name}?charset=utf8mb4"
        else:
            DATABASE_URL: str = f"mysql+pymysql://{_user}@{_host}:{_port}/{_name}?charset=utf8mb4"

    # Tally Prime XML HTTP Configuration
    TALLY_URL: str = os.getenv("TALLY_URL", "http://localhost:9000")
    TALLY_TIMEOUT: int = int(os.getenv("TALLY_TIMEOUT", "10"))
    TALLY_COMPANY_NAME: str = os.getenv("TALLY_COMPANY_NAME", "")
    TALLY_SIMULATION_MODE: bool = os.getenv("TALLY_SIMULATION_MODE", "True").lower() in ("true", "1", "yes")

    # LLM Configuration (Mistral Cloud, Mistral Local, or Ollama) - strictly maintained in .env
    ACTIVE_LLM: str = os.getenv("ACTIVE_LLM", "mistral_local")
    MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    MISTRAL_CHAT_URL: str = os.getenv("MISTRAL_CHAT_URL", "")
    MISTRAL_LOCAL_URL: str = os.getenv("MISTRAL_LOCAL_URL", os.getenv("OLLAMA_URL", ""))
    MISTRAL_LOCAL_MODEL: str = os.getenv("MISTRAL_LOCAL_MODEL", os.getenv("OLLAMA_MODEL", "mistral:latest"))
    AI_CONFIDENCE_THRESHOLD: float = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.80"))

    # Storage & Folder Ingestion Paths (Company-wise Multi-Tenant inside backend/storage)
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))
    INPUT_DIR: str = os.getenv("INPUT_DIR", str(BASE_DIR / "storage" / "input"))
    PROCESSED_DIR: str = os.getenv("PROCESSED_DIR", str(BASE_DIR / "storage" / "processed"))
    ERROR_DIR: str = os.getenv("ERROR_DIR", str(BASE_DIR / "storage" / "error"))

    def get_company_storage_dir(self, company_id: int) -> str:
        """Returns the base storage directory for a specific tenant company."""
        path = os.path.join(self.STORAGE_DIR, "companies", str(company_id))
        os.makedirs(path, exist_ok=True)
        return path

    def get_company_input_dir(self, company_id: int) -> str:
        """Returns the input ingestion directory for a specific tenant company."""
        path = os.path.join(self.get_company_storage_dir(company_id), "input")
        os.makedirs(path, exist_ok=True)
        return path

    def get_company_processed_dir(self, company_id: int) -> str:
        """Returns the processed archive directory for a specific tenant company."""
        path = os.path.join(self.get_company_storage_dir(company_id), "processed")
        os.makedirs(path, exist_ok=True)
        return path

    def get_company_error_dir(self, company_id: int) -> str:
        """Returns the error archive directory for a specific tenant company."""
        path = os.path.join(self.get_company_storage_dir(company_id), "error")
        os.makedirs(path, exist_ok=True)
        return path

    # Security & CORS
    CORS_ORIGINS: list = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(",")
        if o.strip()
    ]
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()

