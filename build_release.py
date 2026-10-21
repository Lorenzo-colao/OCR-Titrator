import os
import shutil
import subprocess
import sys

def main():
    print("Début du processus de création de la version portable...")
    app_base = os.path.dirname(os.path.abspath(__file__))
    
    # Exécuter PyInstaller
    print("1/3 Lancement de PyInstaller (compilation du code)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "OCR Titrateur",
        "--noconfirm",
        "--windowed",
        "--icon=icon.ico",
        "--add-data", f"icon.ico;.",
        "--onedir", # Crée un dossier avec toutes les dépendances
        "--clean",
        os.path.join(app_base, "main.py")
    ]
    subprocess.run(cmd, check=True)
    
    dist_dir = os.path.join(app_base, "dist", "OCR Titrateur")
    
    print("2/3 Copie des dépendances portables (Tesseract et Poppler)...")
    # Tesseract
    tess_src = r"C:\Users\colao\Desktop\OCR_Titrateur\Tesseract-OCR"
    tess_dst = os.path.join(dist_dir, "Tesseract-OCR")
    if os.path.exists(tess_src):
        if not os.path.exists(tess_dst):
            print("  -> Copie de Tesseract...")
            shutil.copytree(tess_src, tess_dst)
    else:
        print(f"  ATTENTION: Tesseract introuvable à {tess_src}")
        
    # Poppler
    # On met Poppler directement dans le dossier "poppler"
    poppler_src = r"C:\Users\colao\Desktop\Roblox game\poppler"
    poppler_dst = os.path.join(dist_dir, "poppler")
    if os.path.exists(poppler_src):
        if not os.path.exists(poppler_dst):
            print("  -> Copie de Poppler...")
            shutil.copytree(poppler_src, poppler_dst)
    else:
        print(f"  ATTENTION: Poppler introuvable à {poppler_src}")
        
    print("3/3 Création de l'archive ZIP portable...")
    zip_path = os.path.join(app_base, "dist", "OCR_Titrateur_Portable")
    shutil.make_archive(zip_path, 'zip', os.path.join(app_base, "dist"), "OCR Titrateur")
    
    print(f"Terminé ! La version portable se trouve dans :\n{zip_path}.zip")

if __name__ == "__main__":
    main()
