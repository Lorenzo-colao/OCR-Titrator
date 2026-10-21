"""Mixin : onglet Fusionner des PDF — design Apple Dark."""
from __future__ import annotations
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import fitz
from gui.theme import Colors, Fonts



def _icon_btn(parent, text, cmd, fg=Colors.TEXT_ON,
              bg=Colors.BG_CARD_ALT, hover=Colors.BG_HOVER) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=Fonts.SANS_LG, bg=bg, fg=fg,
                   padx=10, pady=6, cursor="hand2", relief="flat")
    lbl.bind("<Button-1>", lambda e: cmd())
    lbl.bind("<Enter>",  lambda e: lbl.configure(bg=hover))
    lbl.bind("<Leave>",  lambda e: lbl.configure(bg=bg))
    return lbl


class MergeMixin:
    """Fusion de plusieurs PDFs en un seul document."""

    def _build_merge_tab(self, parent: tk.Frame) -> None:
        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(parent, bg=Colors.BG_PANEL, height=48)
        tb.pack(fill="x", side="top"); tb.pack_propagate(False)
        tk.Frame(parent, bg=Colors.BORDER, height=1).pack(fill="x", side="top")

        _icon_btn(tb, "＋  Ajouter PDF(s)", self.merge_add,
                  fg=Colors.ACCENT, bg=Colors.BG_PANEL,
                  hover=Colors.BG_CARD_ALT).pack(side="left", padx=(14, 6), pady=10)
        _icon_btn(tb, "⊗  Retirer", self.merge_remove,
                  fg=Colors.DANGER, bg=Colors.BG_PANEL,
                  hover=Colors.BG_CARD_ALT).pack(side="left", padx=(0, 6), pady=10)
        tk.Frame(tb, bg=Colors.BORDER, width=1).pack(side="left", fill="y", pady=10, padx=4)
        _icon_btn(tb, "▲  Monter", self.merge_move_up,
                  fg=Colors.TEXT_OFF, bg=Colors.BG_PANEL,
                  hover=Colors.BG_CARD_ALT).pack(side="left", padx=2, pady=10)
        _icon_btn(tb, "▼  Descendre", self.merge_move_down,
                  fg=Colors.TEXT_OFF, bg=Colors.BG_PANEL,
                  hover=Colors.BG_CARD_ALT).pack(side="left", padx=2, pady=10)

        # ── Corps ─────────────────────────────────────────────────────────────
        body = tk.Frame(parent, bg=Colors.BG_DARK)
        body.pack(fill="both", expand=True, padx=20, pady=20)

        # Entête
        hdr = tk.Label(body, text="Fichiers à fusionner  (dans l'ordre de la liste)",
                       font=Fonts.SANS_LG, bg=Colors.BG_DARK, fg=Colors.TEXT_MUTED, anchor="w")
        hdr.pack(anchor="w", pady=(0, 10))

        # Liste card
        list_card = tk.Frame(body, bg=Colors.BG_CARD,
                              highlightbackground=Colors.BORDER, highlightthickness=1)
        list_card.pack(fill="both", expand=True)
        vsb = tk.Scrollbar(list_card, width=6, bg=Colors.BG_CARD,
                            troughcolor=Colors.BG_CARD, relief="flat", bd=0)
        vsb.pack(side="right", fill="y")
        self.merge_listbox = tk.Listbox(
            list_card, yscrollcommand=vsb.set,
            bg=Colors.BG_CARD, fg=Colors.TEXT_ON,
            selectbackground=Colors.ACCENT, selectforeground=Colors.TEXT_ON,
            activestyle="none", font=Fonts.MONO_LG,
            borderwidth=0, highlightthickness=0,
            relief="flat",
        )
        self.merge_listbox.pack(fill="both", expand=True, padx=10, pady=10)
        vsb.config(command=self.merge_listbox.yview)
        self.merge_listbox.bind("<Double-Button-1>", lambda e: self.merge_remove())

        # Info résumé
        self._merge_info = tk.Label(body, text="Aucun fichier ajouté.",
                                     font=Fonts.SANS_SM, bg=Colors.BG_DARK,
                                     fg=Colors.TEXT_MUTED, anchor="w")
        self._merge_info.pack(anchor="w", pady=(10, 0))

    # ── Actions ──────────────────────────────────────────────────────────────

    def merge_add(self) -> None:
        win = self.winfo_toplevel()
        paths = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")], parent=win)
        if not paths:
            win.lift(); win.focus_force(); return
        for p in paths:
            if p in self.merge_paths:
                continue
            if self.pdf_doc is None:
                self._load_pdf(p)
            else:
                self._append_pdf(p)
        self._merge_update_info()
        win.lift(); win.focus_force()

    def _append_pdf(self, path: str) -> None:
        """Ajoute les pages d'un PDF externe au document courant en mémoire."""
        try:
            extra = fitz.open(path)
            start_idx = len(self.pdf_doc)
            self.pdf_doc.insert_pdf(extra)
            extra.close()
            # Étendre page_order avec les nouvelles pages
            new_pages = list(range(start_idx, len(self.pdf_doc)))
            self.page_order.extend(new_pages)
            self.total_pages = len(self.page_order)
            self.lbl_total.configure(text=f"/{self.total_pages}")
            # Mettre à jour la liste fusion
            self.merge_paths.append(path)
            self.merge_listbox.insert("end", f"  {os.path.basename(path)}")
            # Reconstruire les vues
            self._thumb_cache.clear()
            self._invalidate_page_cache()
            self._build_thumbnails()
            self.after(100, lambda: (self._org_compute_card_size(), self._org_rebuild_grid()))
            self._update_status(f"  {len(new_pages)} page(s) ajoutée(s) depuis {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir {os.path.basename(path)} :\n{e}")


    def merge_remove(self) -> None:
        sel = self.merge_listbox.curselection()
        for i in reversed(sel):
            self.merge_listbox.delete(i); self.merge_paths.pop(i)
        self._merge_update_info()

    def merge_move_up(self) -> None:
        sel = self.merge_listbox.curselection()
        if not sel or sel[0] == 0: return
        for i in sel:
            ni = i - 1; item = self.merge_listbox.get(i)
            self.merge_listbox.delete(i); self.merge_listbox.insert(ni, item)
            self.merge_paths.insert(ni, self.merge_paths.pop(i))
        self.merge_listbox.selection_clear(0, "end")
        for i in sel: self.merge_listbox.selection_set(i-1)

    def merge_move_down(self) -> None:
        sel = self.merge_listbox.curselection()
        mx  = self.merge_listbox.size() - 1
        if not sel or sel[-1] == mx: return
        for i in reversed(sel):
            ni = i + 1; item = self.merge_listbox.get(i)
            self.merge_listbox.delete(i); self.merge_listbox.insert(ni, item)
            self.merge_paths.insert(ni, self.merge_paths.pop(i))
        self.merge_listbox.selection_clear(0, "end")
        for i in sel: self.merge_listbox.selection_set(i+1)

    def merge_execute(self) -> None:
        if not self.merge_paths:
            messagebox.showwarning("Aucun PDF", "Ajoutez au moins un PDF à la liste."); return
        save = filedialog.asksaveasfilename(defaultextension=".pdf",
                                             filetypes=[("PDF","*.pdf")],
                                             initialfile="fusion.pdf")
        if not save: return
        try:
            w = fitz.open()
            for p in self.merge_paths:
                with fitz.open(p) as src: w.insert_pdf(src)
            w.save(save); w.close()
            messagebox.showinfo("Fusion réussie ✅",
                                 f"{len(self.merge_paths)} PDF fusionnés :\n{save}")
        except Exception as e:
            messagebox.showerror("Erreur fusion", str(e))

    def _merge_update_info(self) -> None:
        n = len(self.merge_paths)
        if n == 0:
            self._merge_info.configure(text="Aucun fichier ajouté.")
        else:
            self._merge_info.configure(text=f"{n} fichier(s) dans la liste.")
