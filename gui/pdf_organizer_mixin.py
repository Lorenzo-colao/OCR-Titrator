"""Mixin : onglet Organiser les pages — grille drag & drop, design Apple Dark."""
from __future__ import annotations
import os
import tkinter as tk
from tkinter import messagebox, filedialog
import fitz
from PIL import ImageTk
from gui.theme import Colors, Fonts, handle_scroll_y


def _action_btn(parent: tk.Frame, text: str, cmd, fg: str = Colors.TEXT_ON,
                bg: str = Colors.BG_CARD_ALT, hover: str = Colors.BG_HOVER) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=Fonts.SANS_LG, bg=bg, fg=fg,
                   padx=12, pady=6, cursor="hand2", relief="flat")
    lbl.bind("<Button-1>", lambda e: cmd())
    lbl.bind("<Enter>",  lambda e: lbl.configure(bg=hover))
    lbl.bind("<Leave>",  lambda e: lbl.configure(bg=bg))
    return lbl


class OrganizerMixin:
    """Gestionnaire de pages PDF : grille, drag & drop, sélection multiple."""

    def _build_organizer_tab(self, parent: tk.Frame) -> None:
        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = tk.Frame(parent, bg=Colors.BG_PANEL, height=48)
        tb.pack(fill="x", side="top"); tb.pack_propagate(False)
        tk.Frame(parent, bg=Colors.BORDER, height=1).pack(fill="x", side="top")

        _action_btn(tb, "⊗  Supprimer", self.delete_selected_pages,
                    fg=Colors.DANGER, bg=Colors.BG_PANEL,
                    hover=Colors.BG_CARD_ALT).pack(side="left", padx=(14, 6), pady=10)
        _action_btn(tb, "↺  Restaurer tout", self.restore_all_pages,
                    fg=Colors.TEXT_OFF, bg=Colors.BG_PANEL,
                    hover=Colors.BG_CARD_ALT).pack(side="left", padx=(0, 6), pady=10)
        tk.Frame(tb, bg=Colors.BORDER, width=1).pack(side="left", fill="y", pady=10, padx=4)

        for txt, fn in [("⏮", self.move_sel_to_start), ("◀", self.move_sel_backward),
                        ("▶", self.move_sel_forward),   ("⏭", self.move_sel_to_end)]:
            _action_btn(tb, txt, fn, fg=Colors.TEXT_OFF, bg=Colors.BG_PANEL,
                        hover=Colors.BG_CARD_ALT).pack(side="left", padx=1, pady=10)


        self._org_info_lbl = tk.Label(tb, text="", font=Fonts.SANS_SM,
                                       bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED)
        self._org_info_lbl.pack(side="right", padx=12)

        # ── Grille canvas ─────────────────────────────────────────────────────
        grid_host = tk.Frame(parent, bg=Colors.BG_DARK)
        grid_host.pack(fill="both", expand=True)
        vsb = tk.Scrollbar(grid_host, width=6, bg=Colors.BG_DARK,
                            troughcolor=Colors.BG_DARK, relief="flat", bd=0)
        vsb.pack(side="right", fill="y")
        self._org_canvas = tk.Canvas(grid_host, bg=Colors.BG_DARK,
                                      highlightthickness=0, yscrollcommand=vsb.set)
        self._org_canvas.pack(fill="both", expand=True)
        vsb.config(command=self._org_canvas.yview)
        self._org_canvas.bind("<Configure>",       self._org_on_canvas_configure)
        self._org_canvas.bind("<MouseWheel>",      self._org_scroll_y)
        self._org_canvas.bind("<ButtonPress-1>",   self._org_canvas_press)
        self._org_canvas.bind("<B1-Motion>",       self._org_canvas_motion)
        self._org_canvas.bind("<ButtonRelease-1>", self._org_canvas_release)
        self._org_canvas.bind("<Double-Button-1>", self._org_canvas_dblclick)

        # État interne
        self._org_cards = []; self._org_selected = set(); self._org_items = []
        self._drag_card = None; self._drag_ghost = None; self._drag_offset = (0, 0)
        self._drop_target = None; self._drop_line = None
        self._card_width = 160; self._card_height = 220; self._grid_cols = 6
        self._click_idx = None; self._drag_start_x = 0; self._drag_start_y = 0
        self._drag_moved = False; self._autoscroll_speed = 0
        self._org_resize_job = None

        self.after(100, lambda: self.winfo_toplevel().bind(
            "<Delete>", lambda e: self.delete_selected_pages()))

    def _org_on_canvas_configure(self, event) -> None:
        if self._org_resize_job: self.after_cancel(self._org_resize_job)
        w, h = event.width, event.height
        self._org_resize_job = self.after(80, lambda: (
            self._org_compute_card_size(w, h),
            self._org_rebuild_grid(keep_selection=True),
            setattr(self, "_org_resize_job", None)))

    def _org_compute_card_size(self, cw=None, ch=None) -> None:
        cw = cw or self._org_canvas.winfo_width() or 800
        PAD = 12; CW_MAX = 200
        cols = max(1, (cw - PAD) // (CW_MAX + PAD))
        card_w = max(100, min(CW_MAX, (cw - PAD*(cols+1))//cols))
        self._card_width = card_w; self._card_height = int(card_w * 1.5)
        self._grid_cols  = cols

    def _org_scroll_y(self, event) -> None: handle_scroll_y(self._org_canvas, event)

    def _org_rebuild_grid(self, keep_selection: bool = False) -> None:
        if not keep_selection: self._org_selected.clear()
        cv = self._org_canvas; cv.delete("all"); self._org_items.clear(); self._org_cards.clear()
        if not self.pdf_doc or not self.page_order: self._org_update_info(); return
        self._org_compute_card_size()
        CW = self._card_width; CH = self._card_height; PAD = 12; COLS = max(1, self._grid_cols)
        n = len(self.page_order); total_rows = (n + COLS - 1) // COLS
        cv.configure(scrollregion=(0, 0, PAD + COLS*(CW+PAD), PAD + total_rows*(CH+PAD)))
        for idx, orig in enumerate(self.page_order):
            col = idx % COLS; row = idx // COLS
            x = PAD + col*(CW+PAD); y = PAD + row*(CH+PAD)
            self._org_draw_card(idx, orig, x, y, CW, CH)
        self._org_update_info()

    def _org_draw_card(self, idx: int, orig: int, x: int, y: int, CW: int, CH: int) -> None:
        cv = self._org_canvas; is_sel = idx in self._org_selected
        BG     = Colors.BG_CARD_ALT if is_sel else Colors.BG_CARD
        BORDER = Colors.ACCENT      if is_sel else Colors.BORDER
        tag    = f"c{idx}"
        # Card shadow
        cv.create_rectangle(x+2, y+2, x+CW+2, y+CH+2, fill="#000000", outline="", tags=tag)
        # Card bg
        cv.create_rectangle(x, y, x+CW, y+CH, fill=BG, outline=BORDER, width=1, tags=tag)
        # Thumbnail
        tk_img = self._org_get_thumb(orig, (CW-16, CH-44))
        if tk_img:
            cv.create_image(x + CW//2, y + 8 + (CH-44)//2, image=tk_img, tags=tag)
        else:
            cv.create_text(x+CW//2, y+CH//2-20, text="📄", font=("Segoe UI", 22),
                           fill=Colors.TEXT_MUTED, tags=tag)
        # Footer
        cv.create_rectangle(x, y+CH-30, x+CW, y+CH, fill=Colors.BG_PANEL, outline="", tags=tag)
        cv.create_text(x+CW//2, y+CH-15, text=f"Page {idx+1}",
                        font=Fonts.MONO_SM_B, fill=Colors.ACCENT if is_sel else Colors.TEXT_ON,
                        tags=tag)
        if self.crop_pages.get(orig):
            cv.create_text(x+CW-6, y+6, text="✂", font=("Segoe UI", 9),
                           fill=Colors.ACCENT, anchor="ne", tags=tag)
        self._org_items.append((idx, orig, x, y))

    def _org_get_thumb(self, orig: int, size: tuple):
        key = (orig, size)
        if key in self._thumb_cache: return self._thumb_cache[key]
        if not self.pdf_doc or orig >= len(self.pdf_doc): return None
        try:
            page  = self.pdf_doc[orig]
            scale = min(size[0]/page.rect.width, size[1]/page.rect.height)
            pix   = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB)
            img   = ImageTk.PhotoImage(data=pix.tobytes("ppm"))
            self._thumb_cache[key] = img; return img
        except Exception: return None

    def _org_idx_at(self, x, y):
        CW = self._card_width; CH = self._card_height; PAD = 12; COLS = max(1, self._grid_cols)
        col = int((x-PAD)//(CW+PAD)); row = int((y-PAD)//(CH+PAD))
        if col < 0 or col >= COLS: return None
        idx = row*COLS + col
        if not (0 <= idx < len(self.page_order)): return None
        cx = PAD+col*(CW+PAD); cy = PAD+row*(CH+PAD)
        return idx if (cx<=x<=cx+CW and cy<=y<=cy+CH) else None

    def _org_update_info(self) -> None:
        n = len(self.page_order); s = len(self._org_selected)
        text = f"{n} page(s)"
        if s: text += f"  ·  {s} sélectionnée(s)"
        self._org_info_lbl.configure(text=text)

    def _org_canvas_press(self, event) -> None:
        cx = self._org_canvas.canvasx(event.x); cy = self._org_canvas.canvasy(event.y)
        idx = self._org_idx_at(cx, cy)
        self._drag_start_x = event.x_root; self._drag_start_y = event.y_root
        self._drag_moved = False; self._click_idx = idx
        self._click_was_sel = idx in self._org_selected
        if idx is None: return
        ctrl  = (event.state & 0x0004) != 0
        shift = (event.state & 0x0001) != 0
        if ctrl:
            if idx in self._org_selected: self._org_selected.discard(idx)
            else: self._org_selected.add(idx)
        elif shift and self._org_selected:
            anchor = min(self._org_selected); lo, hi = sorted([anchor, idx])
            self._org_selected = set(range(lo, hi+1))
        else:
            if idx not in self._org_selected: self._org_selected = {idx}
        self._org_rebuild_grid(keep_selection=True)

    def _org_canvas_motion(self, event) -> None:
        if self._click_idx is None: return
        dx = abs(event.x_root - self._drag_start_x); dy = abs(event.y_root - self._drag_start_y)
        if not self._drag_moved and (dx > 6 or dy > 6):
            self._drag_moved = True
            self._org_create_ghost(self._click_idx, event.x_root, event.y_root)
            self.bind_all("<MouseWheel>", self._org_wheel_during_drag)
            self._autoscroll_speed = 0
            self._as_ticker = self.after(120, self._org_autoscroll_tick)
        if self._drag_moved and self._drag_ghost:
            self._last_drag_x = event.x_root; self._last_drag_y = event.y_root
            gw = self._drag_ghost.winfo_width(); gh = self._drag_ghost.winfo_height()
            self._drag_ghost.geometry(f"+{event.x_root - gw//2}+{event.y_root - gh//2}")
            self._org_update_drop_indicator(event.x_root, event.y_root)
            cy = self._org_canvas.winfo_height(); ZONE = 60
            self._autoscroll_speed = -1 if event.y < ZONE else (1 if event.y > cy-ZONE else 0)

    def _org_autoscroll_tick(self) -> None:
        if not self._drag_moved: self._as_ticker = None; return
        if self._autoscroll_speed:
            self._org_canvas.yview_scroll(self._autoscroll_speed, "units")
            if hasattr(self, "_last_drag_x"):
                self._org_update_drop_indicator(self._last_drag_x, self._last_drag_y)
        self._as_ticker = self.after(120, self._org_autoscroll_tick)

    def _org_wheel_during_drag(self, event) -> None:
        if not self._drag_moved: return
        handle_scroll_y(self._org_canvas, event)
        if hasattr(self, "_last_drag_x"):
            self._org_update_drop_indicator(self._last_drag_x, self._last_drag_y)

    def _org_canvas_release(self, event) -> None:
        if hasattr(self, "_as_ticker") and self._as_ticker:
            self.after_cancel(self._as_ticker); self._as_ticker = None
        self._autoscroll_speed = 0
        self.unbind_all("<MouseWheel>"); self._org_canvas.bind("<MouseWheel>", self._org_scroll_y)
        if self._drop_line: self._org_canvas.delete(self._drop_line); self._drop_line = None
        if self._drag_ghost: self._drag_ghost.destroy(); self._drag_ghost = None
        if not self._drag_moved:
            if (self._click_idx is not None and self._click_was_sel
                    and not (event.state & 0x0004) and not (event.state & 0x0001)):
                self._org_selected.discard(self._click_idx)
                self._org_rebuild_grid(keep_selection=True)
            self._drag_moved = False; self._drop_target = None; return
        if self._drop_target is None: self._drag_moved = False; return
        self._push_undo("réorganisation")
        moved   = sorted(self._org_selected) if self._org_selected else (
            [self._click_idx] if self._click_idx is not None else [])
        target  = self._drop_target
        items   = [self.page_order[i] for i in moved]
        moved_s = set(moved)
        remaining = [(i, v) for i, v in enumerate(self.page_order) if i not in moved_s]
        ins_pos   = min(sum(1 for i, _ in remaining if i < target), len(remaining))
        self.page_order = ([v for _, v in remaining[:ins_pos]] + items +
                           [v for _, v in remaining[ins_pos:]])
        self._org_selected = set(range(ins_pos, ins_pos+len(items)))
        self._drag_moved = False; self._drop_target = None; self._click_idx = None
        self._org_rebuild_grid(keep_selection=True); self._build_thumbnails()

    def _org_canvas_dblclick(self, event) -> None:
        cx = self._org_canvas.canvasx(event.x); cy = self._org_canvas.canvasy(event.y)
        idx = self._org_idx_at(cx, cy)
        if idx is not None: self._org_show_page_preview(idx)

    def _org_show_page_preview(self, idx: int) -> None:
        if not self.pdf_doc or idx >= len(self.page_order): return
        orig = self.page_order[idx]
        popup = tk.Toplevel(self); popup.configure(bg=Colors.BG_DARK)
        popup.title(f"Aperçu — page {idx+1}")
        popup.attributes("-topmost", True)
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        page  = self.pdf_doc[orig]
        scale = max(0.3, min(min(sw*0.6/page.rect.width, sh*0.75/page.rect.height)*0.9, 3.0))
        pix   = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB)
        img   = ImageTk.PhotoImage(data=pix.tobytes("ppm"))
        iw, ih = pix.width, pix.height
        popup.geometry(f"{iw+40}x{ih+80}+{(sw-iw-40)//2}+{(sh-ih-80)//2}")
        bar = tk.Frame(popup, bg=Colors.BG_PANEL, height=44); bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Label(bar, text=f"  Page {idx+1}", font=Fonts.SANS_XL_B,
                 bg=Colors.BG_PANEL, fg=Colors.TEXT_ON).pack(side="left", padx=12)
        tk.Label(bar, text="✕  Fermer", font=Fonts.SANS_LG,
                 bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED, cursor="hand2",
                 padx=10, pady=10).pack(side="right", padx=8)
        bar.winfo_children()[-1].bind("<Button-1>", lambda e: popup.destroy())
        self._pv_idx = idx

        def nav(d):
            ni = self._pv_idx + d
            if 0 <= ni < len(self.page_order): popup.destroy(); self._org_show_page_preview(ni)
        nav_bar = tk.Frame(popup, bg=Colors.BG_DARK, height=34); nav_bar.pack(fill="x"); nav_bar.pack_propagate(False)
        for txt, d in [("◀  Précédente", -1), ("Suivante  ▶", +1)]:
            side = "left" if d < 0 else "right"
            lbl = tk.Label(nav_bar, text=txt, font=Fonts.SANS_LG,
                           bg=Colors.BG_DARK, fg=Colors.ACCENT, cursor="hand2", padx=10)
            lbl.pack(side=side, padx=8)
            lbl.bind("<Button-1>", lambda e, dd=d: nav(dd))
        cv = tk.Canvas(popup, bg=Colors.BG_DARK, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_image(20, 20, anchor="nw", image=img); cv.configure(scrollregion=(0,0,iw+40,ih+40))
        cv._img = img
        popup.bind("<Escape>", lambda e: popup.destroy())
        popup.bind("<Left>", lambda e: nav(-1)); popup.bind("<Right>", lambda e: nav(+1))
        popup.focus_set()

    def _org_create_ghost(self, idx: int, xr: int, yr: int) -> None:
        if self._drag_ghost: self._drag_ghost.destroy()
        CW = min(self._card_width, 120); CH = int(CW*1.4)
        g = tk.Toplevel(self); g.overrideredirect(True)
        g.attributes("-alpha", 0.80); g.attributes("-topmost", True)
        g.configure(bg=Colors.ACCENT)
        inner = tk.Frame(g, bg=Colors.BG_CARD, padx=2, pady=2)
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        orig = self.page_order[idx]; img = self._org_get_thumb(orig, (CW-16, CH-40))
        if img:
            l = tk.Label(inner, image=img, bg=Colors.BG_CARD); l.image = img; l.pack(pady=(6,2))
        count = max(1, len(self._org_selected))
        if count > 1:
            tk.Label(inner, text=f"  {count} pages", font=Fonts.SANS_SM_B if hasattr(Fonts,"SANS_SM_B") else Fonts.SANS_SM,
                     bg=Colors.ACCENT, fg=Colors.TEXT_ON).place(relx=0, y=0, anchor="nw")
        tk.Label(inner, text=f"Page {idx+1}", font=Fonts.MONO_SM_B,
                 bg=Colors.BG_CARD, fg=Colors.ACCENT).pack()
        g.geometry(f"{CW}x{CH}+{xr-CW//2}+{yr-CH//2}")
        self._drag_ghost = g

    def _org_update_drop_indicator(self, xr: int, yr: int) -> None:
        cx_r = self._org_canvas.winfo_rootx(); cy_r = self._org_canvas.winfo_rooty()
        sx   = self._org_canvas.canvasx(0);    sy   = self._org_canvas.canvasy(0)
        rx = xr - cx_r + sx; ry = yr - cy_r + sy
        CW = self._card_width; CH = self._card_height; PAD = 12; COLS = max(1, self._grid_cols)
        col = max(0, min(int((rx-PAD//2)//(CW+PAD)), COLS-1))
        row = max(0, int((ry-PAD//2)//(CH+PAD)))
        ti  = max(0, min(row*COLS+col, len(self.page_order)))
        if rx - (PAD + col*(CW+PAD)) > CW//2: ti = min(ti+1, len(self.page_order))
        if ti == self._drop_target: return
        self._drop_target = ti
        if self._drop_line: self._org_canvas.delete(self._drop_line)
        ic = ti % COLS; ir = ti // COLS
        lx  = PAD//2 if ic == 0 else PAD + ic*(CW+PAD) - PAD//2
        ly1 = PAD + ir*(CH+PAD) - 4; ly2 = PAD + ir*(CH+PAD) + CH + 4
        self._drop_line = self._org_canvas.create_line(
            lx, ly1, lx, ly2, fill=Colors.ACCENT, width=3, dash=(6, 3))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _org_move_selection(self, delta: int) -> None:
        if not self._org_selected: return
        self._push_undo("déplacement"); order = list(self.page_order); n = len(order)
        for idx in sorted(self._org_selected, reverse=(delta > 0)):
            ni = idx + delta
            if 0 <= ni < n: order[idx], order[ni] = order[ni], order[idx]
        self.page_order = order
        self._org_selected = {min(max(i+delta, 0), n-1) for i in self._org_selected}
        self._org_rebuild_grid(keep_selection=True); self._build_thumbnails()

    def move_sel_forward(self) -> None:  self._org_move_selection(+1)
    def move_sel_backward(self) -> None: self._org_move_selection(-1)

    def move_sel_to_start(self) -> None:
        if not self._org_selected: return
        self._push_undo("début"); sel = sorted(self._org_selected)
        items = [self.page_order[i] for i in sel]
        rest  = [v for i, v in enumerate(self.page_order) if i not in set(sel)]
        self.page_order = items + rest; self._org_selected = set(range(len(items)))
        self._org_rebuild_grid(keep_selection=True); self._build_thumbnails()

    def move_sel_to_end(self) -> None:
        if not self._org_selected: return
        self._push_undo("fin"); sel = sorted(self._org_selected)
        items = [self.page_order[i] for i in sel]
        rest  = [v for i, v in enumerate(self.page_order) if i not in set(sel)]
        self.page_order = rest + items
        self._org_selected = set(range(len(rest), len(rest)+len(items)))
        self._org_rebuild_grid(keep_selection=True); self._build_thumbnails()

    def delete_selected_pages(self) -> None:
        if not self._org_selected:
            messagebox.showwarning("Aucune sélection", "Cliquez sur des pages pour les sélectionner.",
                                   parent=self); self.lift(); return
        if not messagebox.askyesno("Supprimer", f"Supprimer {len(self._org_selected)} page(s) ?",
                                   parent=self):
            self.lift(); return
        self._push_undo("suppression")
        for i in sorted(self._org_selected, reverse=True):
            if i < len(self.page_order): self.deleted.add(self.page_order[i]); self.page_order.pop(i)
        self._org_selected.clear(); self._thumb_cache.clear()
        self.total_pages = len(self.page_order)
        self.current_page = min(self.current_page, max(0, self.total_pages-1))
        self.lbl_total.configure(text=f"/{self.total_pages}")
        self._org_rebuild_grid(); self._build_thumbnails()
        if self.total_pages > 0: self.show_page()
        else: self.canvas.delete("all")

    def restore_all_pages(self) -> None:
        if not self.deleted:
            messagebox.showinfo("Rien à restaurer", "Aucune page supprimée.", parent=self)
            self.lift(); return
        self._push_undo("restauration")
        for orig in sorted(self.deleted): self.page_order.append(orig)
        self.deleted = set(); self.total_pages = len(self.page_order)
        self.lbl_total.configure(text=f"/{self.total_pages}")
        self._thumb_cache.clear(); self._org_rebuild_grid(); self._build_thumbnails(); self.show_page()

    def save_organized_pdf(self) -> None:
        if not self.pdf_doc:
            messagebox.showwarning("Aucun PDF", "Ouvrez d'abord un PDF.", parent=self)
            self.lift(); return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=os.path.splitext(os.path.basename(self.pdf_path))[0] + "_réorganisé.pdf",
            parent=self)
        if not path:
            self.lift(); return
        w = fitz.open()
        for orig in self.page_order:
            w.insert_pdf(self.pdf_doc, from_page=orig, to_page=orig)
        w.save(path)
        messagebox.showinfo("Sauvegardé", f"PDF :\n{path}", parent=self)
        self.lift()
