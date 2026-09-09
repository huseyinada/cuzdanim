"""
Vercel entry point.

Vercel's Python runtime (`@vercel/python`) auto-detects any ASGI app
(FastAPI, Flask, ...) exposed as a module-level `app` and wraps it —
no extra adapter needed. The real application lives in `app/main.py`;
this file just re-exports it so Vercel has a single, tiny entry point.
"""
from app.main import app  # noqa: F401
