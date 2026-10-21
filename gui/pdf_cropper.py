"""
PDFCropperPane — widget principal de l'éditeur PDF.

Remplace ctk.CTkTabview par un onglet plat custom pour
un rendu propre et sans décalage de layout.
"""
from __future__ import annotations
import copy
import os
import tkinter as tk
import fitz

from gui.theme import Colors, Fonts
from gui.pdf_viewer_mixin    import ViewerMixin
from gui.pdf_organizer_mixin import OrganizerMixin
from gui.pdf_merge_mixin     import MergeMixin


class PDFCropperPane(ViewerMixin, OrganizerMixin, MergeMixin, tk.Frame):
    """Panneau d'édition PDF : visualisation, organisation, fusion."""

    PAGE_CACHE_MAX = 8

    _TABS = [
        ("Visualiser & Crop",    "_tab_viewer"),
        ("Organiser les pages",  "_tab_organizer"),
        ("Fusionner des PDF",    "_tab_merge"),
    ]

    def __init__(self, master, **kw) -> None:
        tk.Frame.__init__(self, master, bg=Colors.BG_DARK, **kw)
        self._tab_id         = None
        # ── État document ─────────────────────────────────────────────────────
        self.pdf_doc         = None
        self.pdf_path        = None
        self.current_page    = 0
        self.total_pages     = 0
        self.page_order      = []
        self.deleted         = set()
        self.crop_pages      = {}
        self.merge_paths     = []
        # ── Visionneuse ───────────────────────────────────────────────────────
        self.thumb_btns       = []
        self.thumb_crops      = []
        self._thumb_bg_widgets = []
        self.zoom             = 1.5
        self.zoom_min         = 0.15
        self.zoom_max         = 6.0
        self.mode             = "crop"
        self.rect_start       = None
        self.rect_id          = None
        self._pan_start       = None
        self.tk_img           = None
        self.img_w = self.img_h = 0
        self.offset_x = self.offset_y = 0
        self.on_transfer_to_ocr = None
        self.on_open_in_new_tab  = None  # (path) -> None, défini par PDFEditorWindow
        # ── Undo ──────────────────────────────────────────────────────────────
        self._undo_stack      = []
        self._redo_stack      = []
        self._max_undo        = 50
        # ── Crop handles ──────────────────────────────────────────────────────
        self._resize_handle   = None
        self._resize_orig     = None
        # ── Cache ─────────────────────────────────────────────────────────────
        self._page_cache      = {}
        self._page_cache_keys = []
        self._zoom_job        = None
        self._thumb_cache     = {}
        # ── Build ─────────────────────────────────────────────────────────────
        self._build_ui()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Barre d'onglets custom (flat labels)
        self._tab_bar_frame = tk.Frame(self, bg=Colors.BG_PANEL, height=38)
        self._tab_bar_frame.pack(fill="x", side="top"); self._tab_bar_frame.pack_propagate(False)
        tk.Frame(self, bg=Colors.BORDER, height=1).pack(fill="x", side="top")

        self._tab_labels: dict[str, tk.Label] = {}
        self._tab_indicator: dict[str, tk.Frame] = {}
        self._tab_frames: dict[str, tk.Frame] = {}
        self._active_tab: str = self._TABS[0][0]

        for label, attr in self._TABS:
            # Conteneur tab button
            btn_host = tk.Frame(self._tab_bar_frame, bg=Colors.BG_PANEL, cursor="hand2")
            btn_host.pack(side="left")
            lbl = tk.Label(btn_host, text=label, font=Fonts.SANS_LG,
                           bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED,
                           padx=18, pady=6)
            lbl.pack(side="top")
            # Indicator bar sous le label
            ind = tk.Frame(btn_host, bg=Colors.BG_PANEL, height=2)
            ind.pack(fill="x")
            self._tab_labels[label] = lbl
            self._tab_indicator[label] = ind

            for w in (btn_host, lbl):
                w.bind("<Button-1>", lambda e, n=label: self._switch_tab(n))
                w.bind("<Enter>",  lambda e, bl=lbl: bl.configure(fg=Colors.TEXT_ON)
                       if self._active_tab != bl["text"].strip() else None)
                w.bind("<Leave>",  lambda e, bl=lbl, n=label: bl.configure(
                    fg=Colors.TEXT_ON if self._active_tab == n else Colors.TEXT_MUTED))

            # Frame contenu de l'onglet
            content = tk.Frame(self, bg=Colors.BG_DARK)
            setattr(self, attr, content)
            self._tab_frames[label] = content

        # Construire les contenus
        self._build_viewer_tab(self._tab_viewer)
        self._build_organizer_tab(self._tab_organizer)
        self._build_merge_tab(self._tab_merge)

        # Afficher le premier onglet
        self._switch_tab(self._TABS[0][0])

        # Raccourcis
        win = self.winfo_toplevel()
        win.bind("<Control-z>", lambda e: self._undo())
        win.bind("<Control-Z>", lambda e: self._undo())
        win.bind("<Control-y>", lambda e: self._redo())
        win.bind("<Control-Y>", lambda e: self._redo())

    def _switch_tab(self, label: str) -> None:
        self._active_tab = label
        for name, frame in self._tab_frames.items():
            frame.pack_forget()
        self._tab_frames[label].pack(fill="both", expand=True)
        for name, lbl in self._tab_labels.items():
            is_active = name == label
            lbl.configure(fg=Colors.TEXT_ON if is_active else Colors.TEXT_MUTED,
                           font=(*Fonts.SANS_LG[:2], "bold") if is_active else Fonts.SANS_LG)
            self._tab_indicator[name].configure(
                bg=Colors.ACCENT if is_active else Colors.BG_PANEL)
        # Si on bascule sur le viewer et qu'un PDF est chargé, on rafraîchit
        # (cas typique : PDF ouvert depuis l'onglet Fusion alors que le canvas
        # n'était pas encore visible)
        if label == "Visualiser & Crop" and self.pdf_doc and self.page_order:
            self.after(80, self._zoom_fit_and_show)


    # ── Helpers partagés ──────────────────────────────────────────────────────

    def _sep(self, parent) -> None:
        tk.Frame(parent, bg=Colors.BORDER, width=1).pack(side="left", fill="y", pady=8, padx=4)

    def _tb_btn(self, parent, text, cmd) -> tk.Label:
        """Alias keep compat depuis undo / restore qui s'en servent."""
        from gui.pdf_viewer_mixin import _tb_icon
        btn = _tb_icon(parent, text, cmd)
        btn.pack(side="left", pady=6)
        return btn

    # ── Undo ──────────────────────────────────────────────────────────────────

    def _push_undo(self, label: str = "action") -> None:
        self._undo_stack.append({
            "label":      label,
            "page_order": list(self.page_order),
            "deleted":    set(self.deleted),
            "crop_pages": copy.deepcopy(self.crop_pages),
        })
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self) -> None:
        if not self._undo_stack:
            self._update_status("Rien à annuler"); return
        
        # Sauver l'état actuel dans le redo
        self._redo_stack.append({
            "label":      "Rétablir " + self._undo_stack[-1]["label"],
            "page_order": list(self.page_order),
            "deleted":    set(self.deleted),
            "crop_pages": copy.deepcopy(self.crop_pages),
        })

        snap = self._undo_stack.pop()
        self._apply_snapshot(snap)
        self._update_status(f"Annulé : {snap['label']}")

    def _redo(self) -> None:
        if not self._redo_stack:
            self._update_status("Rien à rétablir"); return

        # Sauver dans l'undo
        self._undo_stack.append({
            "label":      self._redo_stack[-1]["label"].replace("Rétablir ", ""),
            "page_order": list(self.page_order),
            "deleted":    set(self.deleted),
            "crop_pages": copy.deepcopy(self.crop_pages),
        })

        snap = self._redo_stack.pop()
        self._apply_snapshot(snap)
        self._update_status(snap["label"])

    def _apply_snapshot(self, snap: dict) -> None:
        old  = list(self.page_order)
        self.page_order   = snap["page_order"]
        self.deleted      = snap["deleted"]
        self.crop_pages   = snap["crop_pages"]
        self.total_pages  = len(self.page_order)
        self.current_page = min(self.current_page, max(0, self.total_pages-1))
        self.lbl_total.configure(text=f"/{self.total_pages}")
        self._invalidate_page_cache()
        if hasattr(self, "_org_selected"): self._org_selected.clear()
        self._org_rebuild_grid()
        if self.page_order != old:
            self._thumb_cache.clear(); self._build_thumbnails()
        else:
            self._refresh_thumb_crop_badges()
        if self.total_pages > 0: self.show_page()
        else: self.canvas.delete("all")

    def _flash_status(self, msg: str, ms: int = 2500) -> None:
        self.lbl_status.configure(text=f"  {msg}", fg=Colors.ACCENT)
        self.after(ms, self._update_status)

    # ── Capture / restauration (drag entre fenêtres) ──────────────────────────

    def _capture_state(self) -> dict:
        pdf_bytes = None
        if self.pdf_doc:
            try: pdf_bytes = self.pdf_doc.tobytes()
            except Exception: pass
        return {
            "pdf_path":    self.pdf_path,
            "pdf_bytes":   pdf_bytes,
            "merge_paths": list(self.merge_paths),
            "page_order":  list(self.page_order),
            "deleted":     set(self.deleted),
            "crop_pages":  copy.deepcopy(self.crop_pages),
            "current_page":self.current_page,
            "zoom":        self.zoom,
        }

    def _restore_state(self, state: dict) -> None:
        if not state: return
        pdf_bytes = state.get("pdf_bytes")
        if pdf_bytes:
            try: self.pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            except Exception: pass
        if not self.pdf_doc: return
        self.merge_paths   = state.get("merge_paths",  [])
        self.page_order    = state.get("page_order",   list(range(len(self.pdf_doc))))
        self.deleted       = state.get("deleted",      set())
        self.crop_pages    = state.get("crop_pages",   {})
        self.total_pages   = len(self.page_order)
        self.current_page  = min(state.get("current_page", 0), max(0, self.total_pages-1))
        self.zoom          = state.get("zoom", 1.5)
        self.lbl_total.configure(text=f"/{self.total_pages}")
        for b in (self.btn_first, self.btn_prev, self.btn_next, self.btn_last):
            b.configure(fg=Colors.TEXT_ON)
        self.merge_listbox.delete(0, "end")
        for p in self.merge_paths:
            self.merge_listbox.insert("end", f"  {os.path.basename(p)}")
        self._thumb_cache.clear(); self._invalidate_page_cache()
        self._build_thumbnails()
        self.after(100, lambda: (self._org_compute_card_size(), self._org_rebuild_grid()))
        self.after(200, self.show_page)
