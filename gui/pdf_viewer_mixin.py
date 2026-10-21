"""
Mixin : onglet Visualiser & Crop — refonte complète.
Design Apple Dark : toolbar fine, boutons icônes flat, canvas propre.
"""
from __future__ import annotations
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import fitz
from PIL import ImageTk
from gui.theme import Colors, Fonts, handle_scroll_y


# ─── Petits composants internes ───────────────────────────────────────────────

class _Tooltip:
    """Tooltip léger (popup sous le widget au survol)."""
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._w   = widget; self._text = text; self._win = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
    def _show(self, e=None) -> None:
        if self._win: return
        x = self._w.winfo_rootx() + 4
        y = self._w.winfo_rooty() + self._w.winfo_height() + 2
        self._win = tw = tk.Toplevel(self._w)
        tw.overrideredirect(True); tw.attributes("-topmost", True)
        tk.Label(tw, text=self._text, bg="#1C1C1E", fg="#FFFFFF",
                 font=("Segoe UI", 9), padx=8, pady=4, relief="flat").pack()
        tw.geometry(f"+{x}+{y}")
    def _hide(self, e=None) -> None:
        if self._win: self._win.destroy(); self._win = None


def _tb_icon(parent: tk.Frame, text: str, cmd, tooltip: str = "",
             fg: str = Colors.TEXT_ON, bg: str = Colors.BG_PANEL,
             font=None) -> tk.Label:
    """Bouton icône compact (sans width fixe)."""
    lbl = tk.Label(parent, text=text, font=font or ("Segoe UI", 13),
                   bg=bg, fg=fg, cursor="hand2",
                   padx=6, pady=3, relief="flat")
    lbl.bind("<Button-1>", lambda e: cmd())
    lbl.bind("<Enter>",  lambda e: lbl.configure(bg=Colors.BG_CARD_ALT))
    lbl.bind("<Leave>",  lambda e: lbl.configure(bg=bg))
    if tooltip:
        _Tooltip(lbl, tooltip)
    return lbl


def _tb_sep(parent: tk.Frame) -> tk.Frame:
    return tk.Frame(parent, bg=Colors.BORDER, width=1)


def _tb_spacer(parent: tk.Frame) -> tk.Frame:
    return tk.Frame(parent, bg=Colors.BG_PANEL, width=6)


class ViewerMixin:
    """Visualisation PDF : rendu, zoom, navigation, crop."""

    _CURSORS = {
        'nw': 'top_left_corner', 'ne': 'top_right_corner',
        'sw': 'bottom_left_corner', 'se': 'bottom_right_corner',
        'n': 'top_side', 's': 'bottom_side',
        'e': 'right_side', 'w': 'left_side',
    }

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_viewer_tab(self, parent: tk.Frame) -> None:
        # ── Toolbar compacte (icônes + tooltips) ─────────────────────────────
        tb = tk.Frame(parent, bg=Colors.BG_PANEL, height=42)
        self.toolbar_frame = tb
        tb.pack(fill="x", side="top"); tb.pack_propagate(False)
        tk.Frame(parent, bg=Colors.BORDER, height=1).pack(fill="x", side="top")

        _P = dict(side="left", pady=4)   # pack shortcut
        _PS = dict(side="right", pady=4) # pack shortcut right

        # ── Droite en PREMIER ─────────────────────────────────────────────────
        _tb_sep(tb).pack(side="right", fill="y", pady=8, padx=6)

        # ── Gauche ────────────────────────────────────────────────────────────
        # Ouvrir
        _tb_icon(tb, "  📂  Ouvrir PDF  ", self.open_pdf, tooltip="Ouvrir PDF",
                 font=Fonts.SANS_LG, fg=Colors.ACCENT).pack(side="left", padx=(8, 2), pady=4)
        _tb_sep(tb).pack(side="left", fill="y", pady=8, padx=4)

        # Navigation
        self.btn_first = _tb_icon(tb, "⏮", self.go_first, tooltip="Première page",
                                   fg=Colors.TEXT_MUTED)
        self.btn_first.pack(padx=(2, 0), **_P)
        self.btn_prev = _tb_icon(tb, "◀", self.prev_page, tooltip="Page précédente",
                                  fg=Colors.TEXT_MUTED)
        self.btn_prev.pack(**_P)

        self._entry_page = tk.Entry(tb, width=3, justify="center",
                                    font=Fonts.MONO_LG, bg=Colors.BG_CARD,
                                    fg=Colors.TEXT_ON, insertbackground=Colors.TEXT_ON,
                                    relief="flat", bd=0, highlightthickness=1,
                                    highlightbackground=Colors.BORDER,
                                    highlightcolor=Colors.ACCENT)
        self._entry_page.pack(side="left", pady=10, ipady=2, padx=2)
        self._entry_page.bind("<Return>", self.go_to_page)
        self.lbl_total = tk.Label(tb, text="/—", font=Fonts.SANS_SM,
                                   bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED)
        self.lbl_total.pack(side="left", padx=(1, 2))

        self.btn_next = _tb_icon(tb, "▶", self.next_page, tooltip="Page suivante",
                                  fg=Colors.TEXT_MUTED)
        self.btn_next.pack(**_P)
        self.btn_last = _tb_icon(tb, "⏭", self.go_last, tooltip="Dernière page",
                                  fg=Colors.TEXT_MUTED)
        self.btn_last.pack(padx=(0, 2), **_P)

        _tb_sep(tb).pack(side="left", fill="y", pady=8, padx=4)

        _tb_icon(tb, "−", self.zoom_out, tooltip="Zoom arrière",
                 fg=Colors.TEXT_ON).pack(**_P)
        self.lbl_zoom = tk.Label(tb, text="150%", font=Fonts.MONO_SM,
                                  bg=Colors.BG_PANEL, fg=Colors.TEXT_ON, width=5)
        self.lbl_zoom.pack(side="left")
        _tb_icon(tb, "+", self.zoom_in, tooltip="Zoom avant",
                 fg=Colors.TEXT_ON).pack(**_P)
        _tb_icon(tb, "⊞", self.zoom_fit,   tooltip="Ajuster à la fenêtre",
                 fg=Colors.TEXT_OFF).pack(padx=(2, 0), **_P)
        _tb_icon(tb, "1:1", self.zoom_reset, tooltip="Zoom 100%",
                 fg=Colors.TEXT_OFF, font=("Segoe UI", 10)).pack(padx=(1, 0), **_P)

        _tb_sep(tb).pack(side="left", fill="y", pady=8, padx=4)

        self._btn_crop = _tb_icon(tb, "✂", lambda: self.set_mode("crop"),
                                   tooltip="Mode crop", fg=Colors.ACCENT)
        self._btn_crop.pack(**_P)
        self._btn_pan = _tb_icon(tb, "✋", lambda: self.set_mode("pan"),
                                  tooltip="Mode déplacement", fg=Colors.TEXT_OFF)
        self._btn_pan.pack(padx=(2, 0), **_P)
        self._btn_auto = _tb_icon(tb, "✨ Auto", self.auto_crop_current_page,
                                  tooltip="Auto-Crop magique (ignore les unités)", fg=Colors.PURPLE)
        self._btn_auto.pack(padx=(2, 0), **_P)
        _tb_icon(tb, "✕", self.clear_crop, tooltip="Effacer le crop",
                 fg=Colors.DANGER).pack(padx=(2, 0), **_P)

        # ── Corps : sidebar + canvas ───────────────────────────────────────────
        body = tk.Frame(parent, bg=Colors.BG_DARK)
        body.pack(fill="both", expand=True)

        # Sidebar
        sb_host = tk.Frame(body, bg=Colors.BG_PANEL, width=150)
        sb_host.pack(side="left", fill="y"); sb_host.pack_propagate(False)
        tk.Frame(body, bg=Colors.BORDER, width=1).pack(side="left", fill="y")
        sb_bar = tk.Scrollbar(sb_host, width=6, bg=Colors.BG_PANEL,
                               troughcolor=Colors.BG_PANEL, relief="flat", bd=0)
        sb_bar.pack(side="right", fill="y")
        self.sidebar_canvas = tk.Canvas(sb_host, bg=Colors.BG_PANEL,
                                         yscrollcommand=sb_bar.set,
                                         highlightthickness=0)
        self.sidebar_canvas.pack(side="left", fill="both", expand=True)
        sb_bar.config(command=self.sidebar_canvas.yview)
        self.sidebar_frame = tk.Frame(self.sidebar_canvas, bg=Colors.BG_PANEL)
        self.sidebar_canvas.create_window((0, 0), window=self.sidebar_frame, anchor="nw")
        self.sidebar_frame.bind("<Configure>", lambda e: self.sidebar_canvas.config(
            scrollregion=self.sidebar_canvas.bbox("all")))

        # Canvas PDF
        cv_host = tk.Frame(body, bg=Colors.BG_DARK)
        cv_host.pack(side="left", fill="both", expand=True)
        self.hbar = tk.Scrollbar(cv_host, orient="horizontal", width=6,
                                  bg=Colors.BG_DARK, troughcolor=Colors.BG_DARK,
                                  relief="flat", bd=0)
        self.hbar.pack(side="bottom", fill="x")
        self.vbar = tk.Scrollbar(cv_host, orient="vertical", width=6,
                                  bg=Colors.BG_DARK, troughcolor=Colors.BG_DARK,
                                  relief="flat", bd=0)
        self.vbar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(cv_host, bg="#0D0D0D", highlightthickness=0,
                                xscrollcommand=self.hbar.set,
                                yscrollcommand=self.vbar.set)
        self.canvas.pack(fill="both", expand=True)
        self.hbar.config(command=self.canvas.xview)
        self.vbar.config(command=self.canvas.yview)

        # ── Status bar ────────────────────────────────────────────────────────
        sb_frame = tk.Frame(parent, bg=Colors.BG_PANEL, height=24)
        sb_frame.pack(fill="x", side="bottom"); sb_frame.pack_propagate(False)
        tk.Frame(parent, bg=Colors.BORDER, height=1).pack(fill="x", side="bottom")
        self.lbl_status = tk.Label(sb_frame, text="Ouvrez un PDF pour commencer",
                                    font=Fonts.MONO_SM, bg=Colors.BG_PANEL,
                                    fg=Colors.TEXT_MUTED, anchor="w")
        self.lbl_status.pack(side="left", padx=12)
        self.lbl_coords = tk.Label(sb_frame, text="",
                                    font=Fonts.MONO_SM, bg=Colors.BG_PANEL,
                                    fg=Colors.TEXT_MUTED)
        self.lbl_coords.pack(side="right", padx=12)

        # ── Bindings ──────────────────────────────────────────────────────────
        for ev, cb in [
            ("<ButtonPress-1>",   self.on_mouse_down),
            ("<B1-Motion>",       self.on_mouse_drag),
            ("<ButtonRelease-1>", self.on_mouse_up),
            ("<Motion>",          self.on_mouse_move),
            ("<Control-MouseWheel>", self.on_ctrl_scroll),
            ("<MouseWheel>",      self.on_scroll_y),
            ("<Shift-MouseWheel>",self.on_scroll_x),
        ]:
            self.canvas.bind(ev, cb)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        
        def _on_canvas_resize(e):
            lw = getattr(self, '_last_cw', 0)
            lh = getattr(self, '_last_ch', 0)
            if lw > 0 and lh > 0:
                if abs(e.width - lw) > 100 or abs(e.height - lh) > 100:
                    if getattr(self, "_zoom_job", None): self.after_cancel(self._zoom_job)
                    self._zoom_job = self.after(150, lambda: (setattr(self,"_zoom_job",None), self.zoom_fit()))
            self._last_cw = e.width; self._last_ch = e.height

        self.canvas.bind("<Configure>", _on_canvas_resize)
        
        self.sidebar_canvas.bind("<MouseWheel>",  lambda e: handle_scroll_y(self.sidebar_canvas, e))
        self.sidebar_frame.bind("<MouseWheel>",   lambda e: handle_scroll_y(self.sidebar_canvas, e))
        self.after(200, self._bind_keys)

    def _bind_keys(self) -> None:
        win = self.winfo_toplevel()
        for key, fn in [
            ("<Left>",  self.prev_page), ("<Right>", self.next_page),
            ("<Prior>", self.prev_page), ("<Next>",  self.next_page),
            ("<Home>",  self.go_first),  ("<End>",   self.go_last),
            ("<plus>",  self.zoom_in),   ("<equal>", self.zoom_in),
            ("<minus>", self.zoom_out),  ("<space>", self.toggle_mode),
            ("<Control-c>", self.copy_crop), ("<Control-C>", self.copy_crop),
            ("<Control-v>", self.paste_crop), ("<Control-V>", self.paste_crop),
        ]:
            win.bind(key, lambda e, f=fn: f() if callable(f) else None)

    # ── Chargement ────────────────────────────────────────────────────────────

    def open_pdf(self) -> None:
        win = self.winfo_toplevel()
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")], parent=win)
        if path:
            self._load_pdf(path)
            win.lift(); win.focus_force()

    def _load_pdf(self, path: str) -> None:
        self.pdf_path    = path
        self.pdf_doc     = fitz.open(path)
        self.total_pages = len(self.pdf_doc)
        self.page_order  = list(range(self.total_pages))
        self.deleted     = set(); self.crop_pages = {}; self.current_page = 0
        self._thumb_cache.clear(); self._invalidate_page_cache()
        for b in (self.btn_first, self.btn_prev, self.btn_next, self.btn_last):
            b.configure(fg=Colors.TEXT_ON)
        self.lbl_total.configure(text=f"/{self.total_pages}")
        self._notify_tab_rename(os.path.basename(path))
        if path not in self.merge_paths:
            self.merge_paths.append(path)
            self.merge_listbox.insert("end", f"  {os.path.basename(path)}")
        self._build_thumbnails()
        self.after(200, lambda: (self._org_compute_card_size(), self._org_rebuild_grid()))
        self.after(400, self._zoom_fit_and_show)

    def _notify_tab_rename(self, label: str) -> None:
        win = self.winfo_toplevel()
        if hasattr(win, "_tabbar") and self._tab_id is not None:
            win._tabbar.rename_tab(self._tab_id, label)
        try: win.title(f"PDF Editor  —  {label}")
        except Exception: pass

    def transfer_to_ocr(self) -> None:
        if not self.pdf_doc:
            messagebox.showwarning("Aucun PDF", "Ouvrez d'abord un PDF."); return
        if not self.on_transfer_to_ocr:
            messagebox.showwarning("Non disponible",
                                   "Ouvrez l'éditeur depuis la fenêtre principale."); return
        import tempfile
        base     = os.path.splitext(os.path.basename(self.pdf_path or "export"))[0]
        tmp      = os.path.join(tempfile.gettempdir(), f"{base}_editeur_export.pdf")
        try:
            w = fitz.open()
            for idx in self.page_order:
                r = self.crop_pages.get(idx)
                if r:
                    clip = fitz.Rect(*r); p = w.new_page(width=clip.width, height=clip.height)
                    p.show_pdf_page(p.rect, self.pdf_doc, idx, clip=clip)
                else:
                    w.insert_pdf(self.pdf_doc, from_page=idx, to_page=idx)
            w.save(tmp); w.close()
        except Exception as e:
            messagebox.showerror("Erreur", str(e)); return
        self.on_transfer_to_ocr(tmp)

    # ── Rendu ────────────────────────────────────────────────────────────────

    def show_page(self) -> None:
        if not self.pdf_doc or not self.page_order: return
        orig  = self.page_order[self.current_page]
        key   = (orig, round(self.zoom, 2))
        if key in self._page_cache:
            img, iw, ih = self._page_cache[key]
            self._page_cache_keys.remove(key); self._page_cache_keys.append(key)
        else:
            pix = self.pdf_doc[orig].get_pixmap(
                matrix=fitz.Matrix(self.zoom, self.zoom), colorspace=fitz.csRGB)
            img = ImageTk.PhotoImage(data=pix.tobytes("ppm"))
            iw, ih = pix.width, pix.height
            self._page_cache[key] = (img, iw, ih); self._page_cache_keys.append(key)
            if len(self._page_cache_keys) > self.PAGE_CACHE_MAX:
                del self._page_cache[self._page_cache_keys.pop(0)]
        self.tk_img = img; self.img_w = iw; self.img_h = ih
        cw = self.canvas.winfo_width() or 900; ch = self.canvas.winfo_height() or 700
        margin = 20
        self.offset_x = max((cw - iw) // 2, margin)
        self.offset_y = max((ch - ih) // 2, margin)
        tw = max(cw, iw + self.offset_x * 2); th = max(ch, ih + self.offset_y * 2)
        cv = self.canvas; cv.delete("all"); cv.config(scrollregion=(0, 0, tw, th))
        # Ombre de page
        sx, sy = self.offset_x, self.offset_y
        cv.create_rectangle(sx + 3, sy + 3, sx + iw + 3, sy + ih + 3,
                             fill="#000000", outline="")
        cv.create_image(sx, sy, anchor="nw", image=img)
        self._draw_crop_overlay()
        self._entry_page.delete(0, "end"); self._entry_page.insert(0, str(self.current_page + 1))
        self.lbl_zoom.configure(text=f"{int(self.zoom * 100)}%")
        self._highlight_thumb(); self._update_status()

    def _invalidate_page_cache(self, orig_idx=None) -> None:
        if orig_idx is None:
            self._page_cache.clear(); self._page_cache_keys.clear()
        else:
            to_del = [k for k in self._page_cache_keys if k[0] == orig_idx]
            for k in to_del:
                del self._page_cache[k]; self._page_cache_keys.remove(k)

    # ── Crop overlay ─────────────────────────────────────────────────────────

    def _crop_canvas_coords(self):
        if not self.page_order: return None
        r = self.crop_pages.get(self.page_order[self.current_page])
        if not r: return None
        ox, oy = self.offset_x, self.offset_y
        return (ox + r[0]*self.zoom, oy + r[1]*self.zoom,
                ox + r[2]*self.zoom, oy + r[3]*self.zoom)

    def _crop_handle_at(self, cx, cy):
        c = self._crop_canvas_coords()
        if not c: return None
        x1, y1, x2, y2 = c; mx, my = (x1+x2)/2, (y1+y2)/2
        handles = {'nw':(x1,y1),'n':(mx,y1),'ne':(x2,y1),'e':(x2,my),
                   'se':(x2,y2),'s':(mx,y2),'sw':(x1,y2),'w':(x1,my)}
        R = 9
        for name, (hx, hy) in handles.items():
            if abs(cx-hx) <= R and abs(cy-hy) <= R: return name
        return None

    def _draw_crop_overlay(self) -> None:
        self.canvas.delete("crop_overlay")
        if not self.page_order: return
        r = self.crop_pages.get(self.page_order[self.current_page])
        if not r: return
        ox, oy = self.offset_x, self.offset_y
        x1 = ox + r[0]*self.zoom; y1 = oy + r[1]*self.zoom
        x2 = ox + r[2]*self.zoom; y2 = oy + r[3]*self.zoom
        iw, ih = self.img_w, self.img_h
        # Assombrissement hors zone
        for coords in [(ox,oy,ox+iw,y1),(ox,y2,ox+iw,oy+ih),(ox,y1,x1,y2),(x2,y1,ox+iw,y2)]:
            self.canvas.create_rectangle(*coords, fill="#000000", stipple="gray50",
                                          outline="", tags="crop_overlay")
        # Bordure
        self.canvas.create_rectangle(x1, y1, x2, y2, outline=Colors.ACCENT, width=2,
                                      dash=(6, 3), tags="crop_overlay")
        # Handles
        mx, my = (x1+x2)/2, (y1+y2)/2
        for hx, hy in [(x1,y1),(mx,y1),(x2,y1),(x2,my),(x2,y2),(mx,y2),(x1,y2),(x1,my)]:
            self.canvas.create_oval(hx-5, hy-5, hx+5, hy+5,
                                     fill=Colors.ACCENT, outline=Colors.BG_DARK,
                                     width=2, tags="crop_overlay")

    # ── Souris ───────────────────────────────────────────────────────────────

    def _cv(self, event):
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def on_mouse_down(self, event) -> None:
        cx, cy = self._cv(event)
        if self.mode == "pan":
            self._pan_start = (event.x, event.y, self.canvas.canvasx(0), self.canvas.canvasy(0))
            return
        handle = self._crop_handle_at(cx, cy)
        if handle:
            self._push_undo("crop resize"); self._resize_handle = handle
            self._resize_orig = self._crop_canvas_coords(); self.rect_start = None
        else:
            self._resize_handle = None; self.rect_start = (cx, cy)
            if self.rect_id: self.canvas.delete(self.rect_id); self.rect_id = None

    def on_mouse_drag(self, event) -> None:
        cx, cy = self._cv(event)
        if self.mode == "pan" and self._pan_start:
            dx = event.x - self._pan_start[0]; dy = event.y - self._pan_start[1]
            self.canvas.xview_moveto((self._pan_start[2]-dx)/max(self.img_w,1))
            self.canvas.yview_moveto((self._pan_start[3]-dy)/max(self.img_h,1)); return
        if self.mode == "crop":
            if self._resize_handle and self._resize_orig:
                rx1,ry1,rx2,ry2 = self._resize_orig; h = self._resize_handle
                if 'w' in h: rx1 = min(cx, rx2-8)
                if 'e' in h: rx2 = max(cx, rx1+8)
                if 'n' in h: ry1 = min(cy, ry2-8)
                if 's' in h: ry2 = max(cy, ry1+8)
                ox, oy = self.offset_x, self.offset_y
                self.crop_pages[self.page_order[self.current_page]] = (
                    (rx1-ox)/self.zoom, (ry1-oy)/self.zoom,
                    (rx2-ox)/self.zoom, (ry2-oy)/self.zoom)
                self._draw_crop_overlay()
            elif self.rect_start:
                if self.rect_id: self.canvas.delete(self.rect_id)
                self.rect_id = self.canvas.create_rectangle(
                    self.rect_start[0], self.rect_start[1], cx, cy,
                    outline=Colors.ACCENT, width=2, dash=(4, 2))

    def on_mouse_up(self, event) -> None:
        cx, cy = self._cv(event); self._pan_start = None
        if self.mode == "crop":
            if self._resize_handle:
                self._resize_handle = None; self._resize_orig = None
                self._refresh_thumb_crop_badges()
                self._update_status(f"Crop ajusté — page {self.current_page+1}")
            elif self.rect_start:
                x1, y1 = self.rect_start
                rx1, rx2 = sorted([x1, cx]); ry1, ry2 = sorted([y1, cy])
                if rx2-rx1 > 8 and ry2-ry1 > 8:
                    self._push_undo("crop")
                    ox, oy = self.offset_x, self.offset_y
                    self.crop_pages[self.page_order[self.current_page]] = (
                        (rx1-ox)/self.zoom, (ry1-oy)/self.zoom,
                        (rx2-ox)/self.zoom, (ry2-oy)/self.zoom)
                    if self.rect_id: self.canvas.delete(self.rect_id); self.rect_id = None
                    self._draw_crop_overlay(); self._refresh_thumb_crop_badges()
                    self._update_status(f"Crop enregistré — page {self.current_page+1}")
                self.rect_start = None

    def on_mouse_move(self, event) -> None:
        if not self.pdf_doc: return
        cx, cy = self._cv(event)
        if self.mode == "crop":
            h = self._crop_handle_at(cx, cy)
            self.canvas.configure(cursor=self._CURSORS.get(h, "crosshair") if h else "crosshair")
        px = (cx-self.offset_x)/self.zoom; py = (cy-self.offset_y)/self.zoom
        t = f"x : {px:.0f}   y : {py:.0f}"
        if getattr(self, "_lc", None) != t:
            self._lc = t; self.lbl_coords.configure(text=t)

    # ── Navigation ────────────────────────────────────────────────────────────

    def prev_page(self) -> None:
        if self.pdf_doc and self.current_page > 0:
            self.current_page -= 1; self.show_page(); self._scroll_sidebar_to_thumb()
    def next_page(self) -> None:
        if self.pdf_doc and self.current_page < len(self.page_order)-1:
            self.current_page += 1; self.show_page(); self._scroll_sidebar_to_thumb()
    def go_first(self) -> None:
        if self.pdf_doc: self.current_page = 0; self.show_page(); self._scroll_sidebar_to_thumb()
    def go_last(self) -> None:
        if self.pdf_doc:
            self.current_page = len(self.page_order)-1; self.show_page(); self._scroll_sidebar_to_thumb()
    def go_to_page(self, event=None) -> None:
        try:
            n = int(self._entry_page.get()) - 1
            if 0 <= n < len(self.page_order):
                self.current_page = n; self.show_page(); self._scroll_sidebar_to_thumb()
        except ValueError: pass
    def go_to_page_index(self, idx: int) -> None:
        self.current_page = idx; self.show_page()

    # ── Zoom ─────────────────────────────────────────────────────────────────

    def zoom_in(self)  -> None: self.zoom = min(self.zoom*1.25, self.zoom_max); self.show_page()
    def zoom_out(self) -> None: self.zoom = max(self.zoom/1.25, self.zoom_min); self.show_page()
    def zoom_reset(self) -> None: self.zoom = 1.0; self.show_page()
    def zoom_fit(self) -> None:
        if not self.pdf_doc or not self.page_order: return
        page = self.pdf_doc[self.page_order[self.current_page]]
        cw = self.canvas.winfo_width() or 800; ch = self.canvas.winfo_height() or 600
        self.zoom = max(self.zoom_min, min(
            min(cw/page.rect.width, ch/page.rect.height)*0.92, self.zoom_max))
        self.show_page()
    def _zoom_fit_and_show(self) -> None:
        """zoom-fit sûr : attend que le canvas ait des dimensions réelles."""
        self.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            # Canvas pas encore visible (onglet inactif) → réessayer plus tard
            self.after(300, self._zoom_fit_and_show)
            return
        self.zoom_fit()
    def on_ctrl_scroll(self, event) -> None:
        d = getattr(event, "delta", 0)
        if d > 0: self.zoom = min(self.zoom*1.15, self.zoom_max)
        else:     self.zoom = max(self.zoom/1.15, self.zoom_min)
        if self._zoom_job: self.after_cancel(self._zoom_job)
        self._zoom_job = self.after(30, lambda: (setattr(self,"_zoom_job",None), self.show_page()))
    def on_scroll_y(self, event) -> None: handle_scroll_y(self.canvas, event)
    def on_scroll_x(self, event) -> None:
        from gui.theme import handle_scroll_x; handle_scroll_x(self.canvas, event)

    # ── Mode ─────────────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.canvas.configure(cursor="crosshair" if mode == "crop" else "fleur")
        self._btn_crop.configure(fg=Colors.ACCENT   if mode == "crop" else Colors.TEXT_OFF)
        self._btn_pan .configure(fg=Colors.ACCENT   if mode == "pan"  else Colors.TEXT_OFF)
        self._update_status()
    def toggle_mode(self) -> None: self.set_mode("pan" if self.mode == "crop" else "crop")

    # ── Crop actions ─────────────────────────────────────────────────────────

    def auto_crop_current_page(self) -> None:
        """Détecte les données et applique un rognage auto sous les unités (Mettler Toledo/Metrohm)."""
        if not self.pdf_doc or not self.page_order: return
        orig = self.page_order[self.current_page]
        page = self.pdf_doc[orig]
        pw, ph = page.rect.width, page.rect.height
        
        y_top = None
        y_bottom = None
        x_left = 25.0
        x_right = pw - 25.0
        
        # 1. Tentative d'analyse intelligente du texte PDF (très rapide)
        words = page.get_text("words")  # (x0, y0, x1, y1, "text", block_no, line_no, word_no)
        headers = [w for w in words if w[4].strip() in ("mL", "pH")]
        if headers:
            headers.sort(key=lambda x: x[1])  # trier de haut en bas
            header = headers[0]
            # Le crop commence EXACTEMENT sous le mot 'mL' ou 'pH' + marge
            y_top = header[3] + 4.0
            
            # Rechercher la fin
            footers = [w for w in words if "Utilisateur" in w[4] or "Page" in w[4]]
            if footers:
                footers.sort(key=lambda x: x[1], reverse=True)  # de bas en haut
                y_bottom = footers[0][1] - 8.0
            else:
                y_bottom = ph - 30.0
        else:
            # 2. Fallback pour OCR images pures -> Analyse de lignes OpenCV
            try:
                import cv2
                import numpy as np
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                _, thresh = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
                row_sums = np.sum(thresh == 255, axis=1)
                
                # Cherche les lignes hyper longues (50% de largeur)
                line_indices = np.where(row_sums > pix.width * 0.5)[0]
                if len(line_indices) >= 2:
                    first_line_y = line_indices[0] / 2.0
                    last_line_y = line_indices[-1] / 2.0
                    
                    # Saute ~25 pt sous la première ligne pour exclure les unités
                    y_top = first_line_y + 25.0
                    y_bottom = last_line_y - 8.0
            except Exception:
                pass
                
        # 3. Fallback ultime si rien n'a marché
        if y_top is None or y_bottom is None or y_top >= y_bottom:
            y_top = ph * 0.15
            y_bottom = ph * 0.90
            
        self._push_undo("auto-crop")
        self.crop_pages[orig] = (x_left, y_top, x_right, y_bottom)
        self._draw_crop_overlay()
        self._refresh_thumb_crop_badges()
        self._update_status("✅ Auto-Crop appliqué (unités exclues).")

    def clear_crop(self) -> None:
        if getattr(self, "pdf_doc", None):
            self._push_undo("effacement crop")
            self.crop_pages.pop(self.page_order[self.current_page], None)
            self.canvas.delete("crop_overlay"); self._refresh_thumb_crop_badges()
            self._update_status("Crop effacé.")

    def copy_crop(self) -> None:
        if not getattr(self, "pdf_doc", None) or not getattr(self, "page_order", None): return
        orig = self.page_order[self.current_page]
        if orig in self.crop_pages:
            win = self.winfo_toplevel()
            win._global_crop_clipboard = self.crop_pages[orig]
            self._update_status(f"✅ Crop copié (Page {self.current_page+1}).")
        else:
            self._update_status("Aucun crop à copier sur cette page.")

    def paste_crop(self) -> None:
        if not getattr(self, "pdf_doc", None) or not getattr(self, "page_order", None): return
        win = self.winfo_toplevel()
        clip = getattr(win, '_global_crop_clipboard', None)
        if not clip:
            self._update_status("Aucun crop dans le presse-papier.")
            return
        orig = self.page_order[self.current_page]
        self._push_undo("coller crop")
        self.crop_pages[orig] = clip
        self._draw_crop_overlay()
        self._refresh_thumb_crop_badges()
        self._update_status(f"✅ Crop collé (Page {self.current_page+1}).")

    def save_cropped_pdf(self) -> None:
        if not self.pdf_doc:
            messagebox.showwarning("Aucun PDF", "Ouvrez d'abord un PDF."); return
        if not self.crop_pages:
            messagebox.showwarning("Aucun crop", "Définissez au moins une zone de crop."); return
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF","*.pdf")],
            initialfile=os.path.splitext(os.path.basename(self.pdf_path))[0]+"_cropé.pdf")
        if not path: return
        w = fitz.open()
        for idx in self.page_order:
            r = self.crop_pages.get(idx)
            if r:
                clip = fitz.Rect(*r); p = w.new_page(width=clip.width, height=clip.height)
                p.show_pdf_page(p.rect, self.pdf_doc, idx, clip=clip)
            else:
                w.insert_pdf(self.pdf_doc, from_page=idx, to_page=idx)
        w.save(path)
        messagebox.showinfo("Sauvegardé", f"PDF cropé :\n{path}")

    # ── Thumbnails sidebar ────────────────────────────────────────────────────

    def _build_thumbnails(self) -> None:
        for w in self.sidebar_frame.winfo_children(): w.destroy()
        self.thumb_btns = []; self.thumb_crops = []; self._thumb_bg_widgets = []
        if not self.pdf_doc or not self.page_order: return
        self._thumb_build_index = 0; self._thumb_build_step()

    def _thumb_build_step(self) -> None:
        CHUNK = 6; end = min(self._thumb_build_index + CHUNK, len(self.page_order))
        for i in range(self._thumb_build_index, end): self._thumb_build_one(i)
        self._thumb_build_index = end
        if end < len(self.page_order): self.after(0, self._thumb_build_step)

    def _thumb_build_one(self, i: int) -> None:
        orig = self.page_order[i]; key = (orig, "sb")
        if key in self._thumb_cache:
            tk_t = self._thumb_cache[key]
        else:
            pix  = self.pdf_doc[orig].get_pixmap(matrix=fitz.Matrix(0.18, 0.18), colorspace=fitz.csRGB)
            tk_t = ImageTk.PhotoImage(data=pix.tobytes("ppm"))
            self._thumb_cache[key] = tk_t
        frm = tk.Frame(self.sidebar_frame, bg=Colors.BG_PANEL, cursor="hand2", pady=4, padx=6)
        frm.pack(fill="x")
        img_c = tk.Frame(frm, bg=Colors.BG_PANEL); img_c.pack()
        lbl = tk.Label(img_c, image=tk_t, bg=Colors.BG_PANEL, relief="flat", bd=0)
        lbl.image = tk_t; lbl.grid(row=0, column=0)
        badge = tk.Label(img_c, text="✂", font=("Segoe UI", 8, "bold"),
                          bg=Colors.ACCENT, fg=Colors.TEXT_ON, padx=3, pady=1)
        if orig in self.crop_pages: badge.place(relx=1.0, x=-2, y=2, anchor="ne")
        badge._visible = orig in self.crop_pages
        self.thumb_crops.append(badge)
        num = tk.Label(frm, text=str(i+1), font=Fonts.MONO_SM,
                        bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED)
        num.pack()
        self._thumb_bg_widgets.append((frm, img_c, lbl, num))
        for w in (frm, img_c, lbl, num, badge):
            w.bind("<Button-1>", lambda e, idx=i: self.go_to_page_index(idx))
            w.bind("<MouseWheel>", lambda e: handle_scroll_y(self.sidebar_canvas, e))
        self.thumb_btns.append(frm)

    def _highlight_thumb(self) -> None:
        prev = getattr(self, "_thumb_prev", None); curr = self.current_page
        if prev == curr: return
        if prev is not None and prev < len(self._thumb_bg_widgets):
            for w in self._thumb_bg_widgets[prev]:
                try: w.configure(bg=Colors.BG_PANEL)
                except: pass
        if curr < len(self._thumb_bg_widgets):
            for w in self._thumb_bg_widgets[curr]:
                try: w.configure(bg=Colors.BG_CARD)
                except: pass
        self._thumb_prev = curr

    def _scroll_sidebar_to_thumb(self) -> None:
        n = self.total_pages
        if not self.thumb_btns or n == 0: return
        self.sidebar_canvas.yview_moveto(max(0.0, (self.current_page-1)/n))

    def _refresh_thumb_crop_badges(self) -> None:
        for i, badge in enumerate(self.thumb_crops):
            want = (self.page_order[i] if i < len(self.page_order) else -1) in self.crop_pages
            if want != badge._visible:
                if want: badge.place(relx=1.0, x=-2, y=2, anchor="ne")
                else: badge.place_forget()
                badge._visible = want

    def _update_status(self, msg: str | None = None) -> None:
        if not self.pdf_doc: return
        if msg:
            self.lbl_status.configure(text=f"  {msg}"); return
        mode_str = "✂  Crop" if self.mode == "crop" else "✋  Pan"
        text = (f"  Page {self.current_page+1} / {len(self.page_order)}   ·   "
                f"Zoom {int(self.zoom*100)}%   ·   {mode_str}   ·   "
                f"{len(self.crop_pages)} cropée(s)   ·   {len(self.deleted)} supprimée(s)")
        self.lbl_status.configure(text=text)
