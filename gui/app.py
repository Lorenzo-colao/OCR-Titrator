"""
Fenêtre principale — App (Apple Dark Design System)

Layout :
  ┌──────────────────────────────────────────────────────┐
  │  ● Sidebar  (navigation + statut)                    │
  ├──────────────────────────────────────────────────────┤
  │  Content area (Extraction | Paramètres)              │
  └──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import copy
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import CFG, COLONNES, DEFAULT_SETTINGS, Settings, save_settings
from core.ocr_pipeline import process_pdf
from core.excel_export  import export_excel_with_flags
from gui.theme          import Colors, Fonts
from gui.pdf_editor     import PDFEditorWindow
from gui.ocr_preview    import OCRPreviewWindow


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _parse_drop_paths(data: str) -> list[str]:
    matches = re.findall(r'\{([^}]+)\}|(\S+)', data.strip())
    return [m[0] or m[1] for m in matches]


# ── Composants ────────────────────────────────────────────────────────────────

class SpinnerWidget(tk.Canvas):
    """Cercle de chargement animé (spinner) indéterminé."""
    def __init__(self, master, size=24, thickness=3, color=Colors.ACCENT, bg=Colors.BG_DARK, **kwargs) -> None:
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, **kwargs)
        self.size = size
        self.thickness = thickness
        self.color = color
        self.angle = 0
        self._running = False

    def start(self) -> None:
        if self._running: return
        self._running = True
        self._animate()

    def stop(self) -> None:
        self._running = False
        self.delete("arc")

    def _animate(self) -> None:
        if not self._running: return
        self.delete("arc")
        gap = self.thickness // 2 + 1
        d = self.size - gap * 2
        self.create_arc(gap, gap, gap + d, gap + d,
                        start=self.angle, extent=100, outline=self.color,
                        width=self.thickness, style="arc", tags="arc")
        self.angle = (self.angle - 15) % 360
        self.after(30, self._animate)

# ── App ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    """Fenêtre principale — style Apple Dark."""

    _NAV_ITEMS = [
        ("🚀", "Extraction"),
        ("⚙️", "Paramètres"),
    ]

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("OCR Titrateur")
        self.geometry("1080x680")
        self.minsize(820, 520)
        self.configure(fg_color=Colors.BG_DARK)

        self.pdf_files:      list[str]              = []
        self._editor_window: PDFEditorWindow | None = None
        self._worker:        threading.Thread | None = None
        self._stop_event     = threading.Event()
        self._running        = False
        self._log_history:   list[tuple[str, str]]  = []
        self._scalar_entries: dict[str, tuple]      = {}
        self._param_entries:  dict[str, tuple]      = {}
        self._param_errors:   dict[str, tk.StringVar] = {}
        self._active_page    = "Extraction"

        self._build_ui()
        self._setup_drop()
        self._register_listbox_drop()
        self._apply_icon()

    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRUCTION UI
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = tk.Frame(self, bg=Colors.BG_PANEL, width=220)
        sidebar.pack(side="left", fill="y"); sidebar.pack_propagate(False)

        # Logo / titre
        logo_frame = tk.Frame(sidebar, bg=Colors.BG_PANEL)
        logo_frame.pack(fill="x", padx=20, pady=(30, 24))
        tk.Label(logo_frame, text="◎", font=("Segoe UI", 28),
                 bg=Colors.BG_PANEL, fg=Colors.ACCENT).pack(anchor="w")
        tk.Label(logo_frame, text="OCR",
                 font=("Segoe UI", 18, "bold"),
                 bg=Colors.BG_PANEL, fg=Colors.TEXT_ON).pack(anchor="w")
        tk.Label(logo_frame, text="Titrateur",
                 font=("Segoe UI", 11),
                 bg=Colors.BG_PANEL, fg=Colors.TEXT_OFF).pack(anchor="w")

        # Séparateur
        tk.Frame(sidebar, bg=Colors.BORDER, height=1).pack(fill="x", padx=20, pady=(0, 14))

        # Navigation
        self._nav_btns: dict[str, tk.Label] = {}
        for icon, label in self._NAV_ITEMS:
            self._make_nav_btn(sidebar, icon, label)

        # Crédits
        credits_frame = tk.Frame(sidebar, bg=Colors.BG_PANEL)
        credits_frame.pack(side="bottom", fill="x", pady=(0, 16))
        tk.Label(credits_frame, text="Créé par Lorenzo Colao\n© 2026", 
                 font=Fonts.SANS_SM, bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED, 
                 justify="center").pack()

        # Bouton Éditeur PDF en bas de la sidebar
        tk.Frame(sidebar, bg=Colors.BORDER, height=1).pack(fill="x", padx=20, pady=(14, 14), side="bottom")
        editor_btn = tk.Frame(sidebar, bg=Colors.BG_PANEL, cursor="hand2")
        self.btn_editor_pdf = editor_btn
        editor_btn.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        editor_inner = tk.Frame(editor_btn, bg=Colors.BLUE, padx=10, pady=10)
        editor_inner.pack(fill="x")
        tk.Label(editor_inner, text="📝  Éditeur PDF",
                 font=Fonts.SANS_XL_B, bg=Colors.BLUE, fg=Colors.TEXT_ON).pack(anchor="w")
        tk.Label(editor_inner, text="Ouvrir le visualiseur →",
                 font=Fonts.SANS_SM, bg=Colors.BLUE, fg=Colors.TEXT_OFF).pack(anchor="w")
        editor_btn.bind("<Button-1>", lambda e: self.open_cropper())
        for w in editor_inner.winfo_children():
            w.bind("<Button-1>", lambda e: self.open_cropper())
        editor_inner.bind("<Button-1>", lambda e: self.open_cropper())
        editor_btn.bind("<Enter>",  lambda e: [w.configure(bg=Colors.ACCENT_HOVER) for w in (editor_inner, *editor_inner.winfo_children())])
        editor_btn.bind("<Leave>",  lambda e: [w.configure(bg=Colors.BLUE) for w in (editor_inner, *editor_inner.winfo_children())])
        editor_inner.bind("<Enter>",lambda e: [w.configure(bg=Colors.ACCENT_HOVER) for w in (editor_inner, *editor_inner.winfo_children())])
        editor_inner.bind("<Leave>",lambda e: [w.configure(bg=Colors.BLUE) for w in (editor_inner, *editor_inner.winfo_children())])

        # Séparateur vertical
        tk.Frame(self, bg=Colors.BORDER, width=1).pack(side="left", fill="y")

        # ── Zone de contenu principale ─────────────────────────────────────
        self._content_area = tk.Frame(self, bg=Colors.BG_DARK)
        self._content_area.pack(side="left", fill="both", expand=True)

        # Barre de titre / en-tête de page
        self._header_frame = tk.Frame(self._content_area, bg=Colors.BG_DARK, height=72)
        self._header_frame.pack(fill="x"); self._header_frame.pack_propagate(False)
        tk.Frame(self._content_area, bg=Colors.BORDER, height=1).pack(fill="x")

        self._title_lbl = tk.Label(self._header_frame, text="Extraction",
                                    font=("Segoe UI", 20, "bold"),
                                    bg=Colors.BG_DARK, fg=Colors.TEXT_ON)
        self._title_lbl.pack(side="left", padx=32, pady=20)

        self._build_status_dot()

        # Pages empilées (Frame pour chacune)
        self._pages: dict[str, tk.Frame] = {}
        for _, label in self._NAV_ITEMS:
            frame = tk.Frame(self._content_area, bg=Colors.BG_DARK)
            self._pages[label] = frame

        self._build_extraction_page(self._pages["Extraction"])
        self._build_settings_page(self._pages["Paramètres"])
        self._navigate_to("Extraction")

    # ── Sidebar nav button ────────────────────────────────────────────────────

    def _make_nav_btn(self, parent, icon: str, label: str) -> None:
        fr = tk.Frame(parent, bg=Colors.BG_PANEL, cursor="hand2")
        fr.pack(fill="x", padx=10, pady=2)
        inner = tk.Frame(fr, bg=Colors.BG_PANEL, padx=12, pady=10)
        inner.pack(fill="x")
        row = tk.Frame(inner, bg=Colors.BG_PANEL); row.pack(fill="x")
        tk.Label(row, text=icon, font=("Segoe UI", 13),
                 bg=Colors.BG_PANEL, fg=Colors.TEXT_OFF, width=2, anchor="w").pack(side="left")
        lbl = tk.Label(row, text=f"  {label}", font=Fonts.SANS_XL,
                       bg=Colors.BG_PANEL, fg=Colors.TEXT_OFF, anchor="w")
        lbl.pack(side="left", fill="x", expand=True)

        def activate(): self._navigate_to(label)

        def on_enter(e):
            if self._active_page != label:
                inner.configure(bg=Colors.BG_CARD_ALT)
                row.configure(bg=Colors.BG_CARD_ALT)
                for w in row.winfo_children(): w.configure(bg=Colors.BG_CARD_ALT)

        def on_leave(e):
            if self._active_page != label:
                inner.configure(bg=Colors.BG_PANEL)
                row.configure(bg=Colors.BG_PANEL)
                for w in row.winfo_children(): w.configure(bg=Colors.BG_PANEL)

        for w in (fr, inner, row) + tuple(row.winfo_children() if row.winfo_children() else ()):
            w.bind("<Button-1>", lambda e: activate())
            w.bind("<Enter>",    on_enter)
            w.bind("<Leave>",    on_leave)
        self._nav_btns[label] = (fr, inner, row, lbl)

    def _navigate_to(self, label: str) -> None:
        self._active_page = label
        # Hide all pages
        for name, frame in self._pages.items():
            frame.pack_forget()
        # Show requested
        self._pages[label].pack(fill="both", expand=True)
        # Update title
        self._title_lbl.configure(text=label)
        # Update nav highlight
        for name, (fr, inner, row, lbl) in self._nav_btns.items():
            is_active = name == label
            bg = Colors.BG_CARD if is_active else Colors.BG_PANEL
            fg_label = Colors.ACCENT if is_active else Colors.TEXT_OFF
            inner.configure(bg=bg); row.configure(bg=bg)
            for w in row.winfo_children():
                w.configure(bg=bg)
            lbl.configure(fg=fg_label)

    # ── Status dot dans l'en-tête ─────────────────────────────────────────────

    def _build_status_dot(self) -> None:
        fr = tk.Frame(self._header_frame, bg=Colors.BG_DARK)
        fr.pack(side="right", padx=32, pady=20)
        
        self.btn_tuto = self._pill_btn(fr, "  Tutoriel", Colors.BG_CARD_ALT, Colors.BG_HOVER,
                                       self._start_tutorial, text_color=Colors.TEXT_ON, icon="💡")
        self.btn_tuto.pack(side="left", padx=(0, 20))
        
        self._status_dot = tk.Label(fr, text="●", font=("Segoe UI", 11),
                                     bg=Colors.BG_DARK, fg=Colors.TEXT_MUTED)
        self._status_dot.pack(side="left")
        self._status_lbl = tk.Label(fr, text="Prêt", font=Fonts.SANS,
                                     bg=Colors.BG_DARK, fg=Colors.TEXT_OFF)
        self._status_lbl.pack(side="left", padx=(4, 0))

    def _start_tutorial(self) -> None:
        from gui.tutorial import TutorialOverlay
        TutorialOverlay(self)

    def _set_status(self, text: str, color: str = Colors.TEXT_OFF) -> None:
        self._status_dot.configure(fg=color)
        self._status_lbl.configure(text=text)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE EXTRACTION
    # ══════════════════════════════════════════════════════════════════════════

    def _build_extraction_page(self, parent: tk.Frame) -> None:
        outer = tk.Frame(parent, bg=Colors.BG_DARK)
        outer.pack(fill="both", expand=True, padx=32, pady=24)

        # ── Titre section + drop zone ─────────────────────────────────────────
        self._section_label(outer, "Fichiers PDF à traiter")

        drop_card = self._card(outer)
        # Zone de liste
        list_bg = tk.Frame(drop_card, bg=Colors.BG_CARD); list_bg.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        vsb = tk.Scrollbar(list_bg, width=8, bg=Colors.BG_CARD_ALT, troughcolor=Colors.BG_CARD,
                            relief="flat", borderwidth=0)
        vsb.pack(side="right", fill="y")
        self.listbox = tk.Listbox(
            list_bg, yscrollcommand=vsb.set, height=7,
            bg=Colors.BG_CARD, fg=Colors.TEXT_ON,
            selectbackground=Colors.ACCENT, selectforeground=Colors.TEXT_ON,
            activestyle="none", font=Fonts.MONO_LG,
            borderwidth=0, highlightthickness=0,
            relief="flat",
        )
        self.listbox.pack(fill="both", expand=True, padx=14, pady=12)
        vsb.config(command=self.listbox.yview)

        # Boutons
        btn_bar = tk.Frame(drop_card, bg=Colors.BG_CARD); btn_bar.pack(fill="x", padx=16, pady=(10, 12))
        self._pill_btn(btn_bar, "  Ajouter des PDF", Colors.ACCENT, Colors.ACCENT_HOVER,
                       self.add_pdfs, text_color=Colors.TEXT_ON, icon="➕").pack(side="left", padx=(0, 8))
        self._pill_btn(btn_bar, "  Retirer", Colors.BG_CARD_ALT, Colors.BG_HOVER,
                       self.remove_selected, text_color=Colors.TEXT_OFF, icon="➖").pack(side="left", padx=(0, 8))
        self._pill_btn(btn_bar, "  Tout effacer", Colors.BG_CARD_ALT, Colors.BG_HOVER,
                       self.clear_all, text_color=Colors.DANGER, icon="🗑").pack(side="right")

        # ── Dossier de sortie ─────────────────────────────────────────────────
        tk.Frame(outer, bg=Colors.BG_DARK, height=20).pack()
        self._section_label(outer, "Dossier de sortie")
        out_card = self._card(outer)
        out_inner = tk.Frame(out_card, bg=Colors.BG_CARD)
        out_inner.pack(fill="x", padx=14, pady=12)
        self.entry_outdir = ctk.CTkEntry(
            out_inner, height=40, corner_radius=10,
            fg_color=Colors.BG_CARD_ALT, border_color=Colors.BORDER,
            text_color=Colors.TEXT_ON,
            placeholder_text="Choisissez le dossier de sortie…",
            placeholder_text_color=Colors.TEXT_MUTED,
            font=Fonts.SANS_LG,
        )
        self.entry_outdir.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._pill_btn(out_inner, " Parcourir", Colors.BG_CARD_ALT, Colors.BG_HOVER,
                       self.choose_output, text_color=Colors.ACCENT, icon="📁").pack(side="left")

        from config import CFG
        if CFG.output_dir and os.path.exists(CFG.output_dir):
            self.entry_outdir.insert(0, CFG.output_dir)

        # ── Options ───────────────────────────────────────────────────────────
        tk.Frame(outer, bg=Colors.BG_DARK, height=16).pack()
        diag_frame = tk.Frame(outer, bg=Colors.BG_DARK); diag_frame.pack(fill="x")
        self.diag_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(diag_frame, text="    Mode diagnostic (rapport OCR détaillé)",
                         variable=self.diag_var,
                         font=Fonts.SANS_LG,
                         fg_color=Colors.ACCENT,
                         border_color=Colors.BORDER,
                         hover_color=Colors.ACCENT_HOVER,
                         text_color=Colors.TEXT_OFF,
                         ).pack(side="left")

        # ── Actions principales ───────────────────────────────────────────────
        tk.Frame(outer, bg=Colors.BG_DARK, height=24).pack()
        action_row = tk.Frame(outer, bg=Colors.BG_DARK); action_row.pack(fill="x")

        self.btn_run = self._big_btn(action_row, "▶  Lancer l'extraction", Colors.ACCENT,
                                      Colors.ACCENT_HOVER, self.run_extraction)
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_cancel = self._big_btn(action_row, "✕  Annuler", Colors.BG_CARD_ALT,
                                         Colors.BG_HOVER, self._cancel_extraction,
                                         text_color=Colors.DANGER, width=150)
        self.btn_cancel.pack(side="left")

        # ── Indicateur et Console Debug ───────────────────────────────────────
        tk.Frame(outer, bg=Colors.BG_DARK, height=24).pack()
        feedback_card = self._card(outer)
        fb_inner = tk.Frame(feedback_card, bg=Colors.BG_CARD); fb_inner.pack(fill="x", padx=16, pady=12)
        
        self.spinner = SpinnerWidget(fb_inner, size=24, thickness=3, color=Colors.ACCENT, bg=Colors.BG_CARD)
        self.spinner.pack(side="left", padx=(0, 12))
        
        self.lbl_feedback = tk.Label(fb_inner, text="Prêt. Ajoutez des PDF puis lancez l'extraction.", 
                                      font=Fonts.SANS_LG, bg=Colors.BG_CARD, fg=Colors.TEXT_OFF, anchor="w")
        self.lbl_feedback.pack(side="left", fill="x", expand=True)

        self._pill_btn(fb_inner, "  Console Debug", Colors.BG_PANEL, Colors.BG_HOVER,
                       self.open_debug, text_color=Colors.TEXT_OFF, icon="⚙").pack(side="right")

        # ── Historique / Fichiers récents ─────────────────────────────────────
        tk.Frame(outer, bg=Colors.BG_DARK, height=24).pack()
        self._section_label(outer, "Fichiers récents")
        self.history_card = self._card(outer)
        # un peu d'espace direct
        self.history_inner = tk.Frame(self.history_card, bg=Colors.BG_CARD)
        self.history_inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.update_history_ui()

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE PARAMÈTRES
    # ══════════════════════════════════════════════════════════════════════════

    def _build_settings_page(self, parent: tk.Frame) -> None:
        outer = tk.Frame(parent, bg=Colors.BG_DARK)
        outer.pack(fill="both", expand=True)

        scroll_container = tk.Frame(outer, bg=Colors.BG_DARK)
        scroll_container.pack(fill="both", expand=True, padx=32, pady=24)

        scroll = ctk.CTkScrollableFrame(scroll_container, fg_color=Colors.BG_DARK,
                                         scrollbar_button_color=Colors.BG_CARD,
                                         scrollbar_button_hover_color=Colors.BG_HOVER)
        scroll.pack(fill="both", expand=True)

        # ── Section 1 : Plages ───────────────────────────────────────────────
        # Grid 2 colonnes pour les plages
        grid_frame = tk.Frame(scroll, bg=Colors.BG_DARK)
        grid_frame.pack(fill="x")
        col1 = tk.Frame(grid_frame, bg=Colors.BG_DARK); col1.pack(side="left", fill="both", expand=True, padx=(0, 8))
        col2 = tk.Frame(grid_frame, bg=Colors.BG_DARK); col2.pack(side="left", fill="both", expand=True, padx=(8, 0))

        descriptions = {"mL": "Volume titrant", "mL2": "Volume total", "pH": "pH mesuré", 
                        "delta": "ΔpH", "S": "Temps (s)", "C": "Température (°C)"}
        placements = [("mL", col1), ("mL2", col2), ("pH", col1), ("delta", col2), ("S", col1), ("C", col2)]

        for col, parent_col in placements:
            card = self._card(parent_col)
            # Titre & Desc
            top_f = tk.Frame(card, bg=Colors.BG_CARD); top_f.pack(fill="x", padx=16, pady=(16, 8))
            tk.Label(top_f, text=col, font=Fonts.SANS_XL_B, bg=Colors.BG_CARD, fg=Colors.TEXT_ON).pack(side="left")
            tk.Label(top_f, text=descriptions[col], font=Fonts.SANS_SM, bg=Colors.BG_CARD, fg=Colors.TEXT_MUTED).pack(side="left", padx=12)
            
            # Ligne des Inputs
            in_f = tk.Frame(card, bg=Colors.BG_CARD); in_f.pack(fill="x", padx=16, pady=(0, 4))
            tk.Label(in_f, text="Min", font=Fonts.MONO_SM, bg=Colors.BG_CARD, fg=Colors.TEXT_OFF).pack(side="left")
            e_min = self._inline_entry(in_f, width=80); e_min.pack(side="left", padx=(8, 20))
            tk.Label(in_f, text="Max", font=Fonts.MONO_SM, bg=Colors.BG_CARD, fg=Colors.TEXT_OFF).pack(side="left")
            e_max = self._inline_entry(in_f, width=80); e_max.pack(side="left", padx=(8, 0))
            
            # Gestion erreurs
            err_var = tk.StringVar(value="")
            err_lbl = tk.Label(card, textvariable=err_var, font=Fonts.SANS_SM, bg=Colors.BG_CARD, fg=Colors.DANGER, anchor="w")
            err_lbl.pack(fill="x", padx=16, pady=(0, 10))

            self._param_entries[col] = (e_min, e_max)
            self._param_errors[col] = err_var

            for entry in (e_min, e_max):
                entry.bind("<KeyRelease>", lambda e, c=col: self._validate_range(c))
                entry.bind("<FocusOut>",   lambda e, c=col: self._validate_range(c))
            
            tk.Frame(parent_col, bg=Colors.BG_DARK, height=16).pack()

        # ── Section 2 : Scalaires ────────────────────────────────────────────
        tk.Frame(scroll, bg=Colors.BG_DARK, height=20).pack()
        self._section_label(scroll, "Paramètres de traitement")
        scalar_card = self._card(scroll)

        self._scalar_entries = {}
        params = [
            ("scan_dpi",   "DPI de scan",          "Résolution OCR recommandée : 300"),
            ("c_max_step", "Variation max C (°C)",  "Seuil règle R4 température"),
        ]
        for i, (key, label, hint) in enumerate(params):
            row_f = tk.Frame(scalar_card, bg=Colors.BG_CARD)
            row_f.pack(fill="x", padx=18, pady=8)
            left = tk.Frame(row_f, bg=Colors.BG_CARD); left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=label, font=Fonts.SANS_XL_B, bg=Colors.BG_CARD,
                     fg=Colors.TEXT_ON, anchor="w").pack(anchor="w")
            tk.Label(left, text=hint, font=Fonts.SANS_SM, bg=Colors.BG_CARD,
                     fg=Colors.TEXT_MUTED, anchor="w").pack(anchor="w")
            entry = self._inline_entry(row_f, width=120); entry.pack(side="right", padx=(12, 0))
            err_var = tk.StringVar(value="")
            self._scalar_entries[key] = (entry, err_var)

            def _mk_validator(k, e, ev):
                def _v(event=None):
                    raw = e.get().strip().replace(",", ".")
                    try:
                        float(raw); ev.set("")
                        e.configure(border_color=Colors.BORDER)
                    except ValueError:
                        ev.set(f"⚠  invalide"); e.configure(border_color=Colors.DANGER)
                return _v
            v = _mk_validator(key, entry, err_var)
            entry.bind("<KeyRelease>", v); entry.bind("<FocusOut>", v)
            if i < len(params) - 1:
                tk.Frame(scalar_card, bg=Colors.BORDER, height=1).pack(fill="x", padx=14)

        tk.Frame(scalar_card, bg=Colors.BG_CARD, height=8).pack()

        # ── Boutons de sauvegarde ─────────────────────────────────────────────
        tk.Frame(scroll, bg=Colors.BG_DARK, height=20).pack()
        btn_row = tk.Frame(scroll, bg=Colors.BG_DARK); btn_row.pack(fill="x", padx=8)
        self._pill_btn(btn_row, "  Sauvegarder", Colors.ACCENT, Colors.ACCENT_HOVER,
                       self._save_settings, text_color=Colors.TEXT_ON, icon="💾").pack(side="left", padx=(0, 10))
        self._pill_btn(btn_row, "  Valeurs par défaut", Colors.BG_CARD_ALT, Colors.BG_HOVER,
                       self._reset_settings, text_color=Colors.TEXT_OFF, icon="↩").pack(side="left")
        self._settings_status = tk.Label(btn_row, text="", font=Fonts.SANS_LG,
                                          bg=Colors.BG_DARK, fg=Colors.GREEN)
        self._settings_status.pack(side="left", padx=16)

        # ── Redétection des outils ────────────────────────────────────────────
        tk.Frame(scroll, bg=Colors.BG_DARK, height=20).pack()
        tools_card = self._card(scroll)
        tools_inner = tk.Frame(tools_card, bg=Colors.BG_CARD)
        tools_inner.pack(fill="x", padx=14, pady=12)
        tk.Label(tools_inner, text="Outils externes (Tesseract / Poppler)",
                 font=Fonts.SANS_XL_B, bg=Colors.BG_CARD, fg=Colors.TEXT_ON,
                 anchor="w").pack(anchor="w")
        self._tools_lbl = tk.Label(tools_inner, text=self._tools_status_text(),
                                    font=Fonts.SANS_SM, bg=Colors.BG_CARD,
                                    fg=Colors.TEXT_MUTED, anchor="w", justify="left")
        self._tools_lbl.pack(anchor="w", pady=(4, 8))
        self._tools_btn = self._pill_btn(tools_inner, "  Redétecter les outils", Colors.BG_CARD_ALT, Colors.BG_HOVER,
                                         self._reset_tools_detection, text_color=Colors.ACCENT, icon="🔄")
        self._tools_btn.pack(anchor="w")

        self._fill_settings_fields(CFG)
        # Fix scroll wheel — approche robuste : on stocke le scroll frame
        # et on bind récursivement avec retry pour attraper les widgets CTk tardifs
        self._settings_scroll = scroll
        self.after(100, lambda: self._bind_scroll_recursive(scroll))
        self.after(500, lambda: self._bind_scroll_recursive(scroll))

    def _bind_scroll_recursive(self, widget) -> None:
        """Propage le MouseWheel à tous les enfants du CTkScrollableFrame."""
        canvas = getattr(widget, '_parent_canvas', None)
        if canvas is None:
            return
        def fwd(e):
            try: canvas.yview_scroll(int(-1*(e.delta/120)), "units")
            except Exception: pass
        def _bind_deep(w):
            try: w.bind("<MouseWheel>", fwd, add="+")
            except Exception: pass
            for child in w.winfo_children():
                _bind_deep(child)
        _bind_deep(widget)

    def _apply_icon(self) -> None:
        """Applique icon.ico à la fenêtre (compatible script et .exe PyInstaller)."""
        import sys
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__ if "__file__" in dir() else "."))
            base = os.path.join(base, "..")  # gui/ → racine du projet
        ico = os.path.join(base, "icon.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # COMPOSANTS UI RÉUTILISABLES
    # ══════════════════════════════════════════════════════════════════════════

    def _section_label(self, parent, text: str) -> tk.Label:
        lbl = tk.Label(parent, text=text.upper(),
                       font=("Segoe UI", 10, "bold"),
                       bg=Colors.BG_DARK, fg=Colors.TEXT_MUTED,
                       anchor="w", padx=2)
        lbl.pack(fill="x", pady=(0, 8))
        return lbl

    def _card(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=Colors.BG_CARD,
                         highlightbackground=Colors.BORDER, highlightthickness=1)
        frame.pack(fill="x")
        return frame

    def _inline_entry(self, parent, width: int = 100) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(
            parent, width=width, height=36, corner_radius=8,
            fg_color=Colors.BG_CARD_ALT, border_color=Colors.BORDER,
            text_color=Colors.TEXT_ON,
            font=Fonts.MONO_XL, justify="center",
        )

        def _pass_scroll(e):
            # Remonte au parent CTkScrollableFrame pour faire défiler
            w = parent
            while getattr(w, "master", None) is not None:
                if isinstance(w, ctk.CTkScrollableFrame):
                    w._parent_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
                    break
                w = w.master

        def _on_return(e):
            # Enlever le focus au lieu de passer au suivant
            parent.focus()
            return "break"

        # Le vrai input texte ttk/tk est encapsulé dans `_entry` chez CustomTkinter
        if hasattr(entry, "_entry"):
            entry._entry.bind("<MouseWheel>", _pass_scroll, add="+")
            entry._entry.bind("<Return>", _on_return)

        return entry

    def _pill_btn(self, parent, text: str, bg: str, bg_hover: str,
                  command, text_color: str = Colors.TEXT_ON,
                  icon: str = "", height: int = 36) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent, text=f"{icon}{text}", command=command,
            fg_color=bg, hover_color=bg_hover,
            text_color=text_color, font=Fonts.SANS_XL_B,
            height=height, corner_radius=10,
            border_width=0,
        )
        return btn

    def _big_btn(self, parent, text: str, bg: str, bg_hover: str,
                 command, text_color: str = Colors.TEXT_ON,
                 width: int | None = None) -> ctk.CTkButton:
        kw = {"width": width} if width else {}
        return ctk.CTkButton(
            parent, text=text, command=command,
            fg_color=bg, hover_color=bg_hover,
            text_color=text_color, font=Fonts.SANS_XXL_B,
            height=52, corner_radius=14,
            border_width=0, **kw,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PARAMÈTRES — logique
    # ══════════════════════════════════════════════════════════════════════════

    def _validate_range(self, col: str) -> None:
        e_min, e_max = self._param_entries[col]; err = self._param_errors[col]
        try: v_min = float(e_min.get())
        except ValueError: err.set(f"  {col} : min invalide"); return
        try: v_max = float(e_max.get())
        except ValueError: err.set(f"  {col} : max invalide"); return
        if v_min >= v_max:
            err.set(f"  {col} : min ({v_min}) doit être < max ({v_max})")
        else:
            err.set("")

    def _fill_settings_fields(self, cfg_or_dict) -> None:
        if isinstance(cfg_or_dict, Settings):
            vr = cfg_or_dict.validation_rules
            scalar = {k: getattr(cfg_or_dict, k) for k in self._scalar_entries}
        else:
            vr = cfg_or_dict["validation_rules"]
            scalar = {k: cfg_or_dict.get(k, "?") for k in self._scalar_entries}
        for col, (emin, emax) in self._param_entries.items():
            emin.delete(0, "end"); emin.insert(0, str(vr[col]["min"]))
            emax.delete(0, "end"); emax.insert(0, str(vr[col]["max"]))
            self._param_errors[col].set("")
        for key, (entry, _) in self._scalar_entries.items():
            entry.delete(0, "end"); entry.insert(0, str(scalar.get(key, "")))

    def _read_settings(self) -> dict | None:
        errors = []; new = copy.deepcopy(DEFAULT_SETTINGS)
        for col, (emin, emax) in self._param_entries.items():
            try:
                v1, v2 = float(emin.get()), float(emax.get())
                if v1 >= v2: errors.append(f"{col} : min ≥ max")
                else: new["validation_rules"][col]["min"] = v1; new["validation_rules"][col]["max"] = v2
            except ValueError: errors.append(f"{col} : non numérique")
        specs = [("scan_dpi", int, 50), ("c_max_step", float, 0)]
        for key, vtype, vmin in specs:
            try:
                v = vtype(self._scalar_entries[key][0].get())
                if v < vmin: errors.append(f"{key} < {vmin}")
                else: new[key] = v
            except ValueError: errors.append(f"{key} : non numérique")
        if errors:
            messagebox.showerror("Paramètres invalides", "\n".join(f"• {e}" for e in errors))
            return None
        return new

    def _save_settings(self) -> None:
        data = self._read_settings()
        if data is None: return
        CFG.update(data); save_settings(data)
        self._settings_status.configure(text="✓  Paramètres sauvegardés", fg=Colors.GREEN)
        self.after(3000, lambda: self._settings_status.configure(text=""))
        self.log("⚙️  Paramètres mis à jour.")

    def _reset_settings(self) -> None:
        if not messagebox.askyesno("Réinitialiser", "Restaurer les valeurs par défaut ?"): return
        CFG.update(DEFAULT_SETTINGS); save_settings(DEFAULT_SETTINGS)
        self._fill_settings_fields(CFG)
        self._settings_status.configure(text="↩  Valeurs par défaut restaurées", fg=Colors.TEXT_OFF)
        self.after(3000, lambda: self._settings_status.configure(text=""))

    def _tools_status_text(self) -> str:
        from config import TESSERACT_PATH, POPPLER_PATH
        tess = TESSERACT_PATH if TESSERACT_PATH else "introuvable ⚠"
        popp = POPPLER_PATH   if POPPLER_PATH   else "PATH système / introuvable"
        return f"Tesseract : {tess}\nPoppler   : {popp}"

    def _reset_tools_detection(self) -> None:
        """Supprime le cache de détection et relance la recherche des outils."""
        from config.settings import _TOOLS_CACHE_PATH, _find_tesseract, _find_poppler
        import config as _cfg_mod

        if hasattr(self, "_tools_btn"):
            self._tools_btn.configure(text="⏳ Recherche en cours...", text_color=Colors.ORANGE, state="disabled")
            self.update_idletasks()

        try:
            if os.path.isfile(_TOOLS_CACHE_PATH):
                os.remove(_TOOLS_CACHE_PATH)
        except Exception:
            pass

        # Redétection en bloquant le UI principal le temps du scan (max 6s)
        _cfg_mod.TESSERACT_PATH = _find_tesseract()
        _cfg_mod.POPPLER_PATH   = _find_poppler()
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = _cfg_mod.TESSERACT_PATH
        
        # Restaure UI
        if hasattr(self, "_tools_lbl") and self._tools_lbl.winfo_exists():
            self._tools_lbl.configure(text=self._tools_status_text())
        if hasattr(self, "_tools_btn"):
            self._tools_btn.configure(text="🔄  Redétecter les outils", text_color=Colors.ACCENT, state="normal")
            
        self.log(f"🔄  Outils redétectés — Tesseract : {_cfg_mod.TESSERACT_PATH}  |  Poppler : {_cfg_mod.POPPLER_PATH}")

    # ══════════════════════════════════════════════════════════════════════════
    # DRAG & DROP
    # ══════════════════════════════════════════════════════════════════════════

    def _setup_drop(self) -> None:
        """Enregistre la fenêtre et ses widgets clés comme cibles DnD."""
        try:
            from tkinterdnd2 import DND_FILES
            # Fenêtre principale (backdrop)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            # La listbox sera enregistrée après sa création via _register_listbox_drop
        except Exception:
            pass

    def _register_listbox_drop(self) -> None:
        """Enregistre la listbox (et sa zone) comme cible DnD séparée,
        ce qui permet le drop même quand le curseur survole le widget enfant."""
        try:
            from tkinterdnd2 import DND_FILES
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event) -> None:
        added = 0
        for p in _parse_drop_paths(event.data):
            if p.lower().endswith(".pdf") and p not in self.pdf_files:
                self.pdf_files.append(p)
                self.listbox.insert("end", f"  {os.path.basename(p)}")
                added += 1
            elif os.path.isdir(p):
                self.entry_outdir.delete(0, "end")
                self.entry_outdir.insert(0, p)
                self._save_outdir()
        if added:
            self.log(f"📂  {added} fichier(s) ajouté(s) par glisser-déposer.")

    # ══════════════════════════════════════════════════════════════════════════
    # GESTION DES FICHIERS
    # ══════════════════════════════════════════════════════════════════════════

    def add_pdfs(self) -> None:
        for p in filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")]):
            if p not in self.pdf_files:
                self.pdf_files.append(p)
                self.listbox.insert("end", f"  {os.path.basename(p)}")

    def remove_selected(self) -> None:
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i); self.pdf_files.pop(i)

    def clear_all(self) -> None:
        self.listbox.delete(0, "end"); self.pdf_files.clear()

    def choose_output(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.entry_outdir.delete(0, "end")
            self.entry_outdir.insert(0, d)
            self._save_outdir()

    def _save_outdir(self) -> None:
        """Sauvegarde le chemin courant dans les paramètres."""
        d = self.entry_outdir.get().strip()
        from config import CFG, save_settings
        if d and d != CFG.output_dir:
            CFG.output_dir = d
            save_settings(CFG.snapshot())

    def open_cropper(self) -> None:
        if self._editor_window is None or not self._editor_window.winfo_exists():
            self._editor_window = PDFEditorWindow(self, on_transfer_to_ocr=self._receive_from_editor)
        else:
            self._editor_window.new_tab(); self._editor_window.bring_to_front()

    def _receive_from_editor(self, path: str) -> None:
        name = os.path.basename(path)
        if path not in self.pdf_files:
            self.pdf_files.append(path)
            self.listbox.insert("end", f"  [Éditeur] {name}")
            self.log(f"📤  Reçu de l'éditeur : {name}")
        else:
            self.log(f"🔄  Mis à jour : {name}")
        self.lift(); self.focus_force()

    # ══════════════════════════════════════════════════════════════════════════
    # JOURNALISATION
    # ══════════════════════════════════════════════════════════════════════════

    def log(self, msg: str) -> None:
        def _tag():
            if msg.startswith(("✅", "🎉")): return "ok"
            if msg.startswith("❌"): return "error"
            if msg.startswith(("⚠️", "⚙️")): return "warn"
            return "info"
        
        tag = _tag()
        self._log_history.append((msg, tag))

        # 1. Update Feedback label if it's a significant message
        clean_msg = msg.replace('\n', ' ').strip().replace('─', '').replace('═', '').strip()
        if clean_msg and self.lbl_feedback.winfo_exists():
            fg = Colors.TEXT_ON
            if tag == "ok": fg = Colors.GREEN
            elif tag == "error": fg = Colors.DANGER
            self.lbl_feedback.configure(text=clean_msg, fg=fg)

        # 2. Update Console Dialog if opened
        if hasattr(self, '_debug_log_text') and self._debug_log_text.winfo_exists():
            def _do():
                self._debug_log_text.configure(state="normal")
                self._debug_log_text.insert("end", msg + "\n", tag)
                self._debug_log_text.see("end")
                self._debug_log_text.configure(state="disabled")
            self.after(0, _do)

    def open_debug(self) -> None:
        if hasattr(self, '_debug_win') and self._debug_win.winfo_exists():
            self._debug_win.lift()
            return
        
        self._debug_win = tk.Toplevel(self)
        self._debug_win.title("Console de Debug - OCR Titrateur")
        self._debug_win.geometry("800x480")
        self._debug_win.configure(bg=Colors.BG_DARK)
        
        fr = tk.Frame(self._debug_win, bg=Colors.BG_DARK)
        fr.pack(fill="both", expand=True, padx=16, pady=16)
        
        vsb = tk.Scrollbar(fr, width=10, bg=Colors.BG_PANEL, troughcolor=Colors.BG_CARD, relief="flat", borderwidth=0)
        vsb.pack(side="right", fill="y")
        
        self._debug_log_text = tk.Text(
            fr, bg=Colors.BG_CARD, fg=Colors.LOG_GREEN,
            font=Fonts.MONO_LG, wrap="word", borderwidth=0,
            highlightthickness=0, state="normal",
            yscrollcommand=vsb.set,
            padx=16, pady=16,
        )
        self._debug_log_text.pack(fill="both", expand=True)
        vsb.config(command=self._debug_log_text.yview)
        
        self._debug_log_text.tag_configure("ok",    foreground=Colors.GREEN)
        self._debug_log_text.tag_configure("error", foreground=Colors.DANGER)
        self._debug_log_text.tag_configure("warn",  foreground=Colors.ORANGE)
        self._debug_log_text.tag_configure("info",  foreground=Colors.TEXT_OFF)
        
        for m, t in self._log_history:
            self._debug_log_text.insert("end", m + "\n", t)
        self._debug_log_text.see("end")
        self._debug_log_text.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # EXTRACTION
    # ══════════════════════════════════════════════════════════════════════════

    def run_extraction(self) -> None:
        if self._running: return
        if not self.pdf_files:
            messagebox.showwarning("Aucun fichier", "Ajoutez au moins un PDF."); return
        outdir = self.entry_outdir.get().strip()
        if not outdir or not os.path.isdir(outdir):
            messagebox.showwarning("Dossier invalide",
                                   "Choisissez un dossier de sortie valide."); return
        self._save_outdir()
        self._running = True; self._stop_event.clear()
        self.btn_run.configure(state="disabled", text="⏳  Traitement en cours…")
        self.btn_cancel.configure(state="normal", fg_color=Colors.DANGER,
                                   hover_color=Colors.DANGER_ALT)
        self.spinner.start()
        self._set_status("Traitement…", Colors.ORANGE)
        do_diag = self.diag_var.get(); total = len(self.pdf_files)

        def worker():
            try:
                for idx, pdf_path in enumerate(self.pdf_files):
                    if self._stop_event.is_set():
                        self.log("⛔  Interrompu."); break
                    name = os.path.splitext(os.path.basename(pdf_path))[0]
                    self.log(f"\n{'─'*44}\n  [{idx+1}/{total}]  {name}")
                    try:
                        d = os.path.join(outdir, f"{name}_diagnostic_OCR.txt") if do_diag else None
                        df, n, skip, word_boxes, pages_img = process_pdf(
                            pdf_path, self.log, diag_path=d,
                            stop_event=self._stop_event)
                        out = os.path.join(outdir, f"{name}_tableau.xlsx")
                        nf  = export_excel_with_flags(df, out)
                        self.log(f"✅  {n} lignes  →  {name}_tableau.xlsx")
                        if nf: self.log(f"⚠️   {nf} ligne(s) flaggée(s)")

                        # Ajout à l'historique et maj UI
                        from config import CFG
                        CFG.add_recent_file(out)
                        self.after(0, self.update_history_ui)

                        # Ouvrir la preview interactive
                        self.after(0, lambda d=df, p=pdf_path, w=word_boxes, pi=pages_img, o=out:
                                   self._open_ocr_preview(d, p, w, pi, o))

                        if skip:
                            self.log(f"⚙️   {len(skip)} ajustement(s)")
                            for t, r in skip[:3]: self.log(f"      [{t}]  {r[:60]}")
                    except StopIteration:
                        self.log(f"⛔  {name} — interrompu."); break
                    except Exception as e:
                        self.log(f"❌  Erreur : {e}")

                if self._stop_event.is_set():
                    self.after(0, lambda: self._set_status("Annulé", Colors.DANGER))
                else:
                    self.log(f"\n{'═'*44}\n🎉  Terminé ({total} fichier(s))")
                    self.after(0, lambda: self._set_status("Terminé", Colors.GREEN))
            finally:
                self.after(0, self._done)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _cancel_extraction(self) -> None:
        if self._running:
            self._stop_event.set()
            self.btn_cancel.configure(state="disabled", text="⏳  Arrêt…")

    def _done(self) -> None:
        self._running = False; self._stop_event.clear()
        self.btn_run.configure(state="normal", text="▶  Lancer l'extraction")
        self.btn_cancel.configure(state="disabled", text="✕  Annuler",
                                   fg_color=Colors.BG_CARD_ALT, hover_color=Colors.BG_CARD_ALT)
        self.spinner.stop()

    def _open_ocr_preview(self, df, pdf_path, word_boxes, pages_img, out_path) -> None:
        """Ouvre la fenêtre de preview/vérification OCR interactive."""
        try:
            win = OCRPreviewWindow(self, df=df, pdf_path=pdf_path,
                                   word_boxes=word_boxes, pages=pages_img, out_path=out_path)
            win.grab_set()   # mode modale souple
        except Exception as e:
            self.log(f"⚠️  Preview OCR non disponible : {e}")

    def _open_file_history(self, path: str) -> None:
        if os.path.exists(path):
            if messagebox.askyesno("Ouvrir fichier", "Voulez-vous ouvrir ce fichier dans Excel ?\n\n(Répondez 'Non' pour l'ouvrir dans le gestionnaire de prévisualisation interactif de l'application)"):
                try:
                    os.startfile(path)
                except Exception as e:
                    self.log(f"❌  Erreur lors de l'ouverture de {path} : {e}")
            else:
                try:
                    import pandas as pd
                    df = pd.read_excel(path)
                    # Si des colonnes ont été rajoutées par export_excel_with_flags, on les nettoie pour éviter le double-drapeau
                    cols_to_drop = [c for c in ['Ligne', 'Flag', 'Fix_delta', 'Fix_mL2'] if c in df.columns]
                    if cols_to_drop:
                        df = df.drop(columns=cols_to_drop)
                        
                    self._open_ocr_preview(df, path, word_boxes=[], pages_img=[], out_path=path)
                except Exception as e:
                    self.log(f"❌  Impossible de recharger la prévisualisation : {e}")
        else:
            self.log(f"❌  Le fichier {path} n'existe plus.")
            messagebox.showwarning("Fichier introuvable", "Ce fichier semble avoir été déplacé ou supprimé.")

    def update_history_ui(self) -> None:
        from config import CFG
        for widget in self.history_inner.winfo_children():
            widget.destroy()

        recent = CFG.recent_files
        if not recent:
            tk.Label(self.history_inner, text="Aucun fichier récent.", font=Fonts.SANS_LG,
                     bg=Colors.BG_CARD, fg=Colors.TEXT_OFF).pack(pady=10)
            return

        for path in recent[:5]:  # Affiche max 5 fichiers
            row = tk.Frame(self.history_inner, bg=Colors.BG_CARD)
            row.pack(fill="x", pady=2)
            
            # Nom de fichier simple
            name = os.path.basename(path)
            lbl = tk.Label(row, text=name, font=Fonts.SANS_LG, bg=Colors.BG_CARD, fg=Colors.ACCENT, cursor="hand2")
            lbl.pack(side="left", padx=10)
            
            # Sub-label path
            # tk.Label(row, text=path, font=Fonts.SANS_SM, bg=Colors.BG_CARD, fg=Colors.TEXT_MUTED).pack(side="left")
            
            # Clic pour ouvrir
            lbl.bind("<Button-1>", lambda e, p=path: self._open_file_history(p))
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(fg=Colors.TEXT_ON))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(fg=Colors.ACCENT))
            
            # Bouton ouvrir dossier
            def open_dir(p=path):
                folder = os.path.dirname(p)
                if os.path.exists(folder):
                    os.startfile(folder)
            
            folder_icon = tk.Label(row, text="📁", font=Fonts.SANS, bg=Colors.BG_CARD, fg=Colors.TEXT_OFF, cursor="hand2")
            folder_icon.pack(side="right", padx=10)
            folder_icon.bind("<Button-1>", lambda e, p=path: open_dir(p))
            folder_icon.bind("<Enter>", lambda e, w=folder_icon: w.configure(fg=Colors.TEXT_ON))
            folder_icon.bind("<Leave>", lambda e, w=folder_icon: w.configure(fg=Colors.TEXT_OFF))
