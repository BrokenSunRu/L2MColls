@echo off
echo Starting L2M Collections Tracker...
python -m uvicorn main:app --reload
pause