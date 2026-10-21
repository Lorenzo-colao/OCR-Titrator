"""
PDF → Excel | OCR Titrateur
============================
Point d'entrée principal de l'application.

Démarre l'interface graphique et initialise les dépendances.
"""

import sys
import os

# Ajouter le répertoire courant au path pour les imports relatifs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    """Lancement de l'application avec support optionnel du drag & drop."""
    # Tenter d'activer le drag & drop via tkinterdnd2
    try:
        from tkinterdnd2 import TkinterDnD
        import customtkinter.windows.ctk_tk as _ctk_tk
        _ctk_tk.CTK_PARENT_CLASS = TkinterDnD.Tk
    except ImportError:
        pass

    from gui.app import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        import sys
        
        # Get path next to executable or script
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        with open(os.path.join(base_dir, "startup_error_log.txt"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
            
        # Also try to show a popup if possible
        try:
            import tkinter.messagebox as msg
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            msg.showerror("Erreur Fatale", "Le programme a crashé au démarrage.\nRegardez 'startup_error_log.txt' pour les détails.")
        except:
            pass
        sys.exit(1)
