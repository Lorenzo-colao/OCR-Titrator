# OCR Titrateur (PDF → Excel)

Application de bureau moderne développée en Python (CustomTkinter) pour l'extraction OCR de données de titrage depuis des rapports PDF scannés ou numériques vers des feuilles Excel formatées.

## ✨ Fonctionnalités

- **Interface graphique moderne** : Interface claire et ergonomique construite avec CustomTkinter.
- **Pipeline OCR & Prétraitement** : Prise en charge de Tesseract OCR et Poppler avec filtres d'image (OpenCV).
- **Édition et rognage PDF** : Aperçu, réorganisation, fusion et rognage des pages PDF.
- **Validation automatique des données** : Détection des anomalies de valeurs et de cohérence pour les titrages (pH, mL, conductivité, température, etc.).
- **Export Excel stylisé** : Génération de tableaux Excel clairs avec mise en forme conditionnelle et styles de colonnes.

## 🛠️ Prérequis

- **Python 3.10+**
- **Tesseract OCR** (pour l'extraction de texte sur images/scans)
- **Poppler** (pour la conversion de PDF en images)

## 📦 Installation

1. Cloner le dépôt :
   ```bash
   git clone https://github.com/<username>/<repo-name>.git
   cd OCR
   ```

2. Installer les dépendances Python :
   ```bash
   pip install -r requirements.txt
   ```

3. Lancer l'application :
   ```bash
   python main.py
   ```

## 🏗️ Structure du Projet

```text
├── config/             # Paramètres et configurations par défaut
├── core/               # Pipeline OCR, validation des données et export Excel
├── gui/                # Composants de l'interface graphique (CustomTkinter)
├── main.py             # Point d'entrée de l'application
├── requirements.txt    # Dépendances Python
└── build_release.py    # Script de build PyInstaller
```
