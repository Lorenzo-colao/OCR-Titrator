from __future__ import annotations
import tkinter as tk
from gui.theme import Colors, Fonts

def _get_editor_btn(app):
    return getattr(app, "btn_editor_pdf", None)

def _get_settings_nav(app):
    try:
        if hasattr(app, "_nav_btns") and "Paramètres" in app._nav_btns:
            return app._nav_btns["Paramètres"][0]
    except: pass
    return None

class TutorialOverlay(tk.Toplevel):
    """Overlay interactif guidant l'utilisateur pas à pas avec effet Spotlight."""
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.92)
        
        # Transparent color pour percer le trou (Spotlight) sur Windows
        self._hole_color = "#FF00FF"
        try: self.attributes("-transparentcolor", self._hole_color)
        except Exception: pass
        
        self.configure(bg="#0C0F16")
        
        self.steps = [
            {
                "title": "Bienvenue dans OCR Titrateur ! 👋",
                "text": "Ce tutoriel va vous guider à travers les principales fonctionnalités pour extraire et vérifier rapidement vos données.\n\nPrêt à commencer ?",
                "target": None
            },
            {
                "title": "1. Fichiers PDF à traiter 📄",
                "text": "C'est ici que vous ajoutez (ou glissez-déposez) les fichiers PDF contenant les données à extraire.",
                "target": lambda a: getattr(a, "listbox", None).master if hasattr(a, "listbox") else None
            },
            {
                "title": "2. Dossier de sortie 📂",
                "text": "Définissez le répertoire où sera sauvegardé automatiquement le fichier Excel contenant vos résultats.",
                "target": lambda a: getattr(a, "entry_outdir", None).master if hasattr(a, "entry_outdir") else None
            },
            {
                "title": "3. Lancer l'extraction 🚀",
                "text": "Une fois les PDF ajoutés, cliquez sur ce bouton pour démarrer le traitement.\nL'OCR lira les données et générera le tableau avec les anomalies surlignées.",
                "target": lambda a: getattr(a, "btn_run", None)
            },
            {
                "title": "4. Éditeur PDF intégré 📝",
                "text": "Si vos PDF nécessitent d'être rognés (exclure des titres/textes) ou fusionnés avant l'extraction, utilisez cet outil sans même quitter l'application.",
                "target": lambda a: _get_editor_btn(a)
            },
            {
                "title": "5. Paramètres ⚙️",
                "text": "Dans cet onglet, vous configurez toutes les règles scientifiques et statistiques (limites min/max, tolérances...) qui serviront à valider les données.",
                "target": lambda a: _get_settings_nav(a),
                "action": lambda a: a._navigate_to("Paramètres") if hasattr(a, "_navigate_to") else None
            },
            {
                "title": "C'est tout ! 🎉",
                "text": "Vous maîtrisez maintenant l'application.\nEn cas de problème ou de format inconnu, n'hésitez pas à activer la 'Console Debug' pour comprendre ce qui cloche.",
                "target": None,
                "action": lambda a: (a._navigate_to("Extraction") if hasattr(a, "_navigate_to") else None)
            }
        ]
        
        self.current_step = 0
        
        self.canvas = tk.Canvas(self, bg="#0C0F16", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # Info Box (Card)
        self.info_frame = tk.Frame(self.canvas, bg=Colors.BG_CARD, highlightbackground=Colors.BORDER, highlightthickness=1)
        self.lbl_title = tk.Label(self.info_frame, text="", font=Fonts.SANS_XL_B, bg=Colors.BG_CARD, fg=Colors.TEXT_ON, justify="left")
        self.lbl_title.pack(anchor="w", padx=20, pady=(20, 10))
        self.lbl_text = tk.Label(self.info_frame, text="", font=Fonts.SANS_LG, bg=Colors.BG_CARD, fg=Colors.TEXT_MUTED, justify="left", wraplength=380)
        self.lbl_text.pack(anchor="w", padx=20, pady=(0, 20))
        
        # Navigation boutons dans Info Box
        nav = tk.Frame(self.info_frame, bg=Colors.BG_CARD)
        nav.pack(fill="x", padx=20, pady=(0, 20))
        
        self.btn_prev = tk.Label(nav, text="◀ Précédent", font=Fonts.SANS_LG, bg=Colors.BG_CARD, fg=Colors.TEXT_OFF, cursor="hand2")
        self.btn_prev.pack(side="left")
        self.btn_prev.bind("<Button-1>", lambda e: self.prev_step())
        
        self.btn_next = tk.Label(nav, text="Suivant ▶", font=Fonts.SANS_LG_B, bg=Colors.ACCENT, fg=Colors.TEXT_ON, cursor="hand2", padx=16, pady=8)
        self.btn_next.pack(side="right")
        self.btn_next.bind("<Button-1>", lambda e: self.next_step())
        
        # Overlay Close Button
        self.btn_close = tk.Label(self.canvas, text="✕  Passer le tutoriel", font=Fonts.SANS_LG, bg="#0C0F16", fg=Colors.TEXT_MUTED, cursor="hand2")
        self.btn_close.place(relx=0.98, rely=0.03, anchor="ne")
        self.btn_close.bind("<Button-1>", lambda e: self.destroy())
        self.btn_close.bind("<Enter>", lambda e: self.btn_close.configure(fg=Colors.TEXT_ON))
        self.btn_close.bind("<Leave>", lambda e: self.btn_close.configure(fg=Colors.TEXT_MUTED))
        
        self.app.bind("<Configure>", self.sync_geometry, add="+")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<ButtonPress-1>", self.on_bg_click)
        
        # Rend les clics hors du tuto inopérants
        self.grab_set()
        
        self.sync_geometry()
        self.app.after(50, self.show_step)
        self.focus_force()

    def destroy(self):
        self.grab_release()
        super().destroy()

    def sync_geometry(self, *args):
        if not self.winfo_exists(): return
        self.geometry(f"{self.app.winfo_width()}x{self.app.winfo_height()}+{self.app.winfo_rootx()}+{self.app.winfo_rooty()}")
        if args and self.winfo_viewable():
            self.show_step()

    def show_step(self):
        self.canvas.delete("all")
        step = self.steps[self.current_step]
        
        # Check action associées (ex: naviguer vers onglet)
        if "action" in step and step["action"] is not None:
            step["action"](self.app)
            self.update_idletasks() # pour être sûr du positionnement
            
        self.lbl_title.configure(text=step["title"])
        self.lbl_text.configure(text=step["text"])
        
        if self.current_step == 0:
            self.btn_prev.pack_forget()
        else:
            self.btn_prev.pack(side="left")
            
        if self.current_step == len(self.steps) - 1:
            self.btn_next.configure(text="Terminer ✔", bg=Colors.GREEN)
        else:
            self.btn_next.configure(text="Suivant ▶", bg=Colors.ACCENT)
            
        target_fn = step["target"]
        target_widget = target_fn(self.app) if callable(target_fn) else None
        
        w, h = self.winfo_width(), self.winfo_height()
        
        # Draw background base hole and border
        target_rect = None
        if target_widget and target_widget.winfo_exists() and target_widget.winfo_viewable():
            tx, ty = target_widget.winfo_rootx() - self.winfo_rootx(), target_widget.winfo_rooty() - self.winfo_rooty()
            tw, th = target_widget.winfo_width(), target_widget.winfo_height()
            pad = 8
            x1, y1 = max(0, tx - pad), max(0, ty - pad)
            x2, y2 = min(w, tx + tw + pad), min(h, ty + th + pad)
            
            # Draw the mask : tout est dessiné en noir 0C0F16 par défaut
            self.canvas.create_rectangle(0, 0, w, h, fill="#0C0F16", outline="")
            
            # Draw the Spotlight hole
            self.canvas.create_rectangle(x1, y1, x2, y2, fill=self._hole_color, outline=Colors.ACCENT, width=2, dash=(6, 4))
            
            # Positionner la carte info proche du widget
            iw, ih = 430, 240 # approx
            px = x2 + 20
            py = y1
            if px + iw > w:
                px = x1 - iw - 20   # On met à gauche
            if px < 0:
                px = max(20, w / 2 - iw / 2) # On met au milieu
                py = y2 + 20                # En dessous
                if py + ih > h:
                    py = y1 - ih - 20       # Au dessus
                    
            self.canvas.create_window(px, py, window=self.info_frame, anchor="nw")
            
        else:
            self.canvas.create_rectangle(0, 0, w, h, fill="#0C0F16", outline="")
            self.canvas.create_window(w / 2, h / 2, window=self.info_frame, anchor="center")

    def next_step(self):
        if self.current_step < len(self.steps) - 1:
            self.current_step += 1
            self.show_step()
        else:
            self.destroy()

    def prev_step(self):
        if self.current_step > 0:
            self.current_step -= 1
            self.show_step()
            
    def on_bg_click(self, event):
        # Ne ferme pas en cliquant sur le fond, l'utilisateur doit lire et cliquer 'Suivant'
        pass

class PDFEditorTutorialOverlay(TutorialOverlay):
    """Tutoriel interactif spécifique pour l'Éditeur PDF."""
    
    def __init__(self, app) -> None:
        # Configuration des étapes propres à l'éditeur PDF
        super().__init__(app)
        
        self.steps = [
            {
                "title": "L'Éditeur PDF 📝",
                "text": "Bienvenue dans l'éditeur PDF ! Ici, vous pouvez préparer vos documents manuellement avant de lancer l'extraction OCR.\n\nVous êtes prêt ?",
                "target": None
            },
            {
                "title": "1. Mode de Traitement 🗂️",
                "text": "Cet outil possède 3 modes : Visualisation/Rognage, Organisation de pages (tri et suppression), et Fusion de plusieurs PDF.\n\nSélectionnez l'onglet souhaité selon vos besoins.",
                "target": lambda a: a._active_pane()._tab_bar_frame if (hasattr(a, "_active_pane") and a._active_pane() is not None) else None
            },
            {
                "title": "2. Outils de Rognage ✂️",
                "text": "Dans le mode Visualisation, utilisez cette barre pour zoomer, dessiner des Rognages manuels, ou utiliser l'Auto-Crop magique pour couper les en-têtes.",
                "target": lambda a: a._active_pane().toolbar_frame if (hasattr(a, "_active_pane") and a._active_pane() is not None and hasattr(a._active_pane(), "toolbar_frame")) else None
            },
            {
                "title": "3. Annuler / Rétablir ↩️",
                "text": "Pas de panique ! En cas d'erreur de rognage ou de suppression de page, vous pouvez annuler avec ces boutons ou Ctrl+Z (Windows).",
                "target": lambda a: a._action_bar if hasattr(a, "_action_bar") else None
            },
            {
                "title": "4. Exporter vers l'OCR 📤",
                "text": "Une fois votre PDF parfaitement propre et rogné, transférez-le directement dans le moteur d'OCR avec ce bouton, ou sauvegardez-le sur votre PC.",
                "target": lambda a: a.btn_send_ocr if hasattr(a, "btn_send_ocr") else None
            },
            {
                "title": "Fin ! 🎉",
                "text": "Vous êtes paré(e). N'hésitez pas à jouer avec les outils pour préparer au mieux vos documents sans avoir besoin d'un autre logiciel !",
                "target": None
            }
        ]
        
        # Le rafraîchissement se lance automatiquement grâce à super().__init__
