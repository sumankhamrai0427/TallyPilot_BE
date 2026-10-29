"""Application settings controller handling runtime settings and integration diagnostics.
Follows the EduJunction Flask controller pattern.
"""
from flask import request, jsonify
from database.dbConnection import SessionLocal
from database.repositories import SettingsRepository
from helper.local_llm import LocalLLMService
from helper.tally_client import TallyClientService


def get_settings():
    """Retrieves system configuration and integration diagnostics."""
    db = SessionLocal()
    try:
        repo = SettingsRepository(db)
        current_settings = repo.get_all()

        llm = LocalLLMService()
        tally = TallyClientService()

        llm_health = llm.check_health()
        tally_health = tally.test_connection()

        return jsonify({
            "configurations": current_settings,
            "diagnostics": {
                "llm": llm_health,
                "tally": tally_health
            }
        })
    finally:
        db.close()


def update_settings():
    """Updates runtime application settings."""
    payload = request.get_json(silent=True) or {}
    settings_dict = payload.get("settings", {})

    db = SessionLocal()
    try:
        repo = SettingsRepository(db)
        for k, v in settings_dict.items():
            repo.set(k, str(v))
        return jsonify({"success": True, "settings": repo.get_all()})
    finally:
        db.close()
