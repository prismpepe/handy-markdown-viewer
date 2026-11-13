@echo off
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name MarkdownViewer --add-data "ui.html;." --add-data "deck.js;." --add-data "deck.css;." --add-data "deck_ui.js;." --add-data "vendor;vendor" --add-data "print.js;." --add-data "vfind.js;." mdviewer.py
echo.
echo dist\MarkdownViewer.exe
