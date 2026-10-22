@echo off
uv run uvicorn --port 8000 --factory fintrack_core.main:create_app
