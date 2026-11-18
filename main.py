"""Compatibility entry point for the LiAInne backend.

Run the app exactly as before: uvicorn main:app
"""
from backend.main import app

__all__ = ["app"]
