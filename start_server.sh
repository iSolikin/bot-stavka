#!/bin/bash
# Start the web server
python -m uvicorn web_app:app --host 0.0.0.0 --port 8000 --reload
