"""
PDFEditorWindow — fenêtre multi-onglets pour l'éditeur PDF.

Utilise exactement l'API réelle de TabBar :
  add_tab(label, select_cb, close_cb) → tid (géré par TabBar)
"""
from __future__ import annotations
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox
from gui.theme   import Colors, Fonts
from gui.tab_bar import TabBar
from gui.pdf_cropper import PDFCropperPane


def _parse_drop_paths(data: str) -> list[str]:
    matches = re.findall(r'\{([^}]+)\}|(\S+)', data.strip())
    return [m[0] or m[1] for m in matches]


class PDFEditorWindow(tk.Toplevel):
    """Fenêtre autonome hébergeant plusieurs PDFCropperPane via TabBar."""

    def __init__(self, master, on_transfer_to_ocr=None, **kw) -> None:
        super().__init__(master, **kw)
        self.title("PDF Editor")
        self.geometry("1200x760"); self.minsize(900, 560)
        self.configure(bg=Colors.BG_DARK)
        self.on_transfer_to_ocr = on_transfer_to_ocr
        # mapping: TabBar-generated tid → PDFCropperPane
        self._panes: dict[int, PDFCropperPane] = {}
        self._current_tid: int | None = None
        self._drop_overlay: tk.Frame | None = None
        self._build_ui()
        self.new_tab()
        self._setup_drop()
        # Icône
        try:
            import sys
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
                   else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
            ico = os.path.join(base, "icon.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._tabbar = TabBar(
            self,
            on_new_tab = self.new_tab,
            on_detach  = self._on_detach,
            on_receive = self._on_receive,
        )
        self._tabbar.pack(fill="x", side="top")
        tk.Frame(self, bg=Colors.BORDER, height=1).pack(fill="x", side="top")

        self._content = tk.Frame(self, bg=Colors.BG_DARK)
        self._content.pack(fill="both", expand=True)

        # ── Barre d'actions globale ─────────────────────────────────────────────
        self._action_bar = tk.Frame(self, bg=Colors.BG_PANEL, height=46)
        self._action_bar.pack(fill="x", side="top", before=self._content)
        self._action_bar.pack_propagate(False)
        tk.Frame(self, bg=Colors.BORDER, height=1).pack(fill="x", side="top", before=self._content)

        def _ab_btn(text, fg, cmd):
            lbl = tk.Label(self._action_bar, text=text, font=Fonts.SANS_LG_B,
                           bg=Colors.BG_PANEL, fg=fg, padx=14, pady=10, cursor="hand2")
            lbl.bind("<Button-1>", lambda e: cmd())
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=Colors.BG_CARD_ALT))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=Colors.BG_PANEL))
            return lbl

        _ab_btn("↶  Annuler", Colors.TEXT_ON, self._global_undo).pack(side="left", padx=(10, 2))
        _ab_btn("↷  Rétablir", Colors.TEXT_ON, self._global_redo).pack(side="left", padx=(2, 10))
        tk.Frame(self._action_bar, bg=Colors.BORDER, width=1).pack(side="left", fill="y", pady=10)
        
        _ab_btn("💾  Sauvegarder PDF", Colors.GREEN,  self._global_save_pdf).pack(side="left", padx=(10, 4))
        tk.Frame(self._action_bar, bg=Colors.BORDER, width=1).pack(side="left", fill="y", pady=10)
        self.btn_send_ocr = _ab_btn("📤  Envoyer à l'OCR", Colors.ACCENT, self._global_send_to_ocr)
        self.btn_send_ocr.pack(side="left", padx=(4, 0))
        
        # Bouton Tuto
        self.btn_tuto = _ab_btn("💡  Tutoriel", Colors.TEXT_ON, self._start_tutorial)
        self.btn_tuto.configure(fg=Colors.TEXT_MUTED)
        self.btn_tuto.pack(side="right", padx=(0, 20))

    def _start_tutorial(self) -> None:
        from gui.tutorial import PDFEditorTutorialOverlay
        PDFEditorTutorialOverlay(self)

    # ── Tab management ────────────────────────────────────────────────────────

    def new_tab(self) -> PDFCropperPane:
        """Crée un nouvel onglet + PDFCropperPane et l'active."""
        pane = PDFCropperPane(self._content)
        pane.on_transfer_to_ocr = self.on_transfer_to_ocr

        # On enregistre temporairement pour que les callbacks trouvent le pane
        # TabBar génère son propre tid — on le récupère au retour de add_tab
        _tmp = []

        def _on_select():
            tid = _tmp[0] if _tmp else None
            if tid is not None:
                self._show_pane(tid)

        def _on_close():
            tid = _tmp[0] if _tmp else None
            if tid is not None:
                self._close_tab(tid)

        label = f"Sans titre"
        tid   = self._tabbar.add_tab(label, select_cb=_on_select, close_cb=_on_close)
        _tmp.append(tid)

        pane._tab_id = tid
        self._panes[tid] = pane
        self._show_pane(tid)
        return pane

    def _show_pane(self, tid: int) -> None:
        """Affiche uniquement le panneau de l'onglet actif."""
        self._current_tid = tid
        for t, p in self._panes.items():
            p.pack_forget()
        if tid in self._panes:
            self._panes[tid].pack(fill="both", expand=True)
            label = self._tabbar.get_label(tid)
            self.title(f"PDF Editor  —  {label}")

    def _close_tab(self, tid: int) -> None:
        """Ferme un onglet et son panneau."""
        if tid in self._panes:
            self._panes[tid].destroy()
            del self._panes[tid]
        self._tabbar.remove_tab(tid)
        if not self._panes:
            self.destroy()
        elif self._current_tid == tid:
            last = list(self._panes.keys())[-1]
            self._tabbar.set_active(last)
            self._show_pane(last)

    # ── Détachement ───────────────────────────────────────────────────────────

    def _on_detach(self, tid: int, ax: int, ay: int,
                   target_bar=None, insert_pos: int = 0) -> None:
        if tid not in self._panes: return
        state = self._panes[tid]._capture_state()
        label = self._tabbar.get_label(tid)
        self._close_tab(tid)

        if target_bar is not None:
             target_win = target_bar.winfo_toplevel()
             if hasattr(target_win, '_on_receive'):
                  new_pane = PDFCropperPane(target_win._content)
                  new_pane.on_transfer_to_ocr = target_win.on_transfer_to_ocr
                  new_pane._restore_state(state)
                  target_win._on_receive(None, new_pane, label, insert_pos=insert_pos)
                  return

        win = PDFEditorWindow(self.master, on_transfer_to_ocr=self.on_transfer_to_ocr)
        new_pane = list(win._panes.values())[0]
        new_pane._restore_state(state)
        win._tabbar.rename_tab(list(win._panes.keys())[0], label)
        win.geometry(f"+{ax}+{ay}")

    def _on_receive(self, tid, pane: PDFCropperPane, label: str, insert_pos: int = -1) -> None:
        """Reçoit un onglet détaché d'une autre fenêtre."""
        pane.pack_forget(); pane.pack = pane.pack  # reset geometry manager
        _tmp = []

        def _on_select():
            t = _tmp[0] if _tmp else None
            if t: self._show_pane(t)

        def _on_close():
            t = _tmp[0] if _tmp else None
            if t: self._close_tab(t)

        if insert_pos >= 0:
            new_tid = self._tabbar.insert_tab(insert_pos, label, select_cb=_on_select, close_cb=_on_close)
        else:
            new_tid = self._tabbar.add_tab(label, select_cb=_on_select, close_cb=_on_close)
            
        _tmp.append(new_tid)
        pane._tab_id = new_tid
        self._panes[new_tid] = pane
        self._show_pane(new_tid)


    # ── Drag & Drop ───────────────────────────────────────────────────────────

    def _setup_drop(self) -> None:
        """Enregistre cette fenêtre comme cible DnD."""
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            self.dnd_bind("<<Drop>>",      self._on_drop)
        except Exception:
            pass

    def _show_drop_overlay(self) -> None:
        if self._drop_overlay is not None:
            return
        overlay = tk.Frame(self, bg="#040F1C", cursor="hand2")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        canvas = tk.Canvas(overlay, bg="#040F1C", highlightthickness=0)
        canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        canvas.bind("<Configure>", lambda e, c=canvas: self._draw_overlay_content(c))
        self._drop_overlay = overlay
        self._overlay_canvas = canvas
        overlay.lift()

    def _draw_overlay_content(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 2 or h < 2:
            return
        cx, cy = w // 2, h // 2
        r = min(w, h) // 7
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=Colors.ACCENT, width=4, fill="#071828")
        arm = int(r * 0.5)
        lw = max(4, int(r * 0.1))
        canvas.create_line(cx - arm, cy, cx + arm, cy,
                           fill=Colors.ACCENT, width=lw, capstyle="round")
        canvas.create_line(cx, cy - arm, cx, cy + arm,
                           fill=Colors.ACCENT, width=lw, capstyle="round")
        canvas.create_text(cx, cy + r + 28, text="Déposer un PDF pour l'ouvrir",
                           fill=Colors.TEXT_ON, font=("Segoe UI", 14, "bold"))

    def _hide_drop_overlay(self) -> None:
        if self._drop_overlay is not None:
            self._drop_overlay.destroy()
            self._drop_overlay = None

    def _on_drag_enter(self, event) -> None:
        self._show_drop_overlay()
        if hasattr(self, "_overlay_canvas"):
            self.after(10, lambda: self._draw_overlay_content(self._overlay_canvas))

    def _on_drag_leave(self, event) -> None:
        self._hide_drop_overlay()

    def _on_drop(self, event) -> None:
        self._hide_drop_overlay()
        for p in _parse_drop_paths(event.data):
            if p.lower().endswith(".pdf"):
                pane = self.new_tab()
                pane._load_pdf(p)

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def _active_pane(self) -> PDFCropperPane | None:
        """Retourne le PDFCropperPane de l'onglet actuellement actif."""
        if self._current_tid is not None:
            return self._panes.get(self._current_tid)
        return None

    def _global_save_pdf(self) -> None:
        """Sauvegarde le PDF de l'onglet actif en appliquant réarrangement, suppressions et crops."""
        pane = self._active_pane()
        if pane is None or not pane.pdf_doc:
            messagebox.showwarning("Aucun PDF", "Ouvrez d'abord un PDF.", parent=self)
            self.lift(); return
        label = self._tabbar.get_label(self._current_tid)
        base  = os.path.splitext(label)[0]
        path  = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"{base}_modifié.pdf", parent=self)
        if not path:
            self.lift(); return
        try:
            import fitz
            w = fitz.open()
            for orig in pane.page_order:
                # Appliquer le crop si défini pour cette page
                r = pane.crop_pages.get(orig)
                if r:
                    clip = fitz.Rect(*r)
                    p = w.new_page(width=clip.width, height=clip.height)
                    p.show_pdf_page(p.rect, pane.pdf_doc, orig, clip=clip)
                else:
                    w.insert_pdf(pane.pdf_doc, from_page=orig, to_page=orig)
            w.save(path); w.close()
            messagebox.showinfo("✅  Sauvegardé", f"PDF enregistré :\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Erreur", str(e), parent=self)
        self.lift()

    def _global_send_to_ocr(self) -> None:
        """Envoie le document traité à l'OCR de l'appli source."""
        if not self.on_transfer_to_ocr:
            messagebox.showinfo("OCR", "La fonction d'extraction OCR n'est pas connectée.", parent=self)
            self.lift(); return
        pane = self._active_pane()
        if pane:
            pane.transfer_to_ocr()
            messagebox.showinfo("✅  Envoyé", f"Fichier envoyé à l'OCR :\n{pane.pdf_path}", parent=self)
        else:
            messagebox.showwarning("Non disponible",
                                   "Enregistrez d'abord le PDF, puis utilisez 'Envoyer à l'OCR' depuis l'éditeur.",
                                   parent=self)
        self.lift()

    def _global_undo(self) -> None:
        """Annule la dernière action du panneau courant."""
        pane = self._active_pane()
        if pane: pane._undo()

    def _global_redo(self) -> None:
        """Rétablit l'action annulée du panneau courant."""
        pane = self._active_pane()
        if pane: pane._redo()

    def bring_to_front(self) -> None:
        self.lift(); self.focus_force()
