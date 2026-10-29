"""Controller package initialization.
Exports all controllers for app.py explicit endpoint delegation (matching EduJunction).
"""
from controller import (
    dashboard_controller,
    files_controller,
    transactions_controller,
    tally_controller,
    logs_controller,
    settings_controller,
)

__all__ = [
    "dashboard_controller",
    "files_controller",
    "transactions_controller",
    "tally_controller",
    "logs_controller",
    "settings_controller",
]
