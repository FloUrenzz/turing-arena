@echo off
chcp 65001 >nul
title Turing Arena v3
cd /d "%~dp0.."
echo Turing Arena v3
python -B -X utf8 main.py --chat --corpus data/dialogue-combined-5350-v2.sqlite3 %*
pause
