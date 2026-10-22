@echo off
uv run uvicorn --port 8001 --factory fintrack_advisor.main:create_app
