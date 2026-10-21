@echo off
echo ====================================================
echo Compilation de OCR Titrateur avec PyInstaller...
echo ====================================================
rmdir /s /q dist\OCR_Titrateur 2>nul
rmdir /s /q build\OCR_Titrateur 2>nul
pyinstaller --clean --noconfirm --onedir --name "OCR_Titrateur" --hidden-import openpyxl --hidden-import pandas --hidden-import pdf2image  --collect-all customtkinter --collect-all tkinterdnd2 --icon=icon.ico --noconsole --add-data "icon.ico;." --add-data "icon.png;." main.py
echo.
echo ====================================================
echo TERMINE !
echo Vous pouvez maintenant coller les dossiers "poppler" et "Tesseract-OCR" dans "dist/OCR_Titrateur"
echo Et double-cliquer sur "OCR_Titrateur.exe"
echo S'il y a un probleme, lisez la console apparue ou startup_error_log.txt !
echo ====================================================
pause
