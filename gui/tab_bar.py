"""
Barre d'onglets dessinée sur Canvas (drag & drop, réordonnement, détachement).

Widget autonome réutilisable qui gère :
- Affichage et sélection d'onglets
- Réordonnement par glisser-déposer
- Détachement vers une autre fenêtre (cross-window drag)
- Bouton de fermeture et bouton « + »
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from gui.theme import Colors


class TabBar(tk.Canvas):
    """
    Barre d'onglets custom dessinée sur un ``tk.Canvas``.

    Supporte le drag interne (réordonnement), le drag externe
    (détachement vers une autre fenêtre) et les callbacks de sélection/fermeture.
    """

    TAB_H      = 36
    TAB_MIN_W  = 130
    TAB_MAX_W  = 260
    PAD_X      = 12
    PAD_BTN    = 10
    BTN_R      = 8

    C_BG        = Colors.BG_DARK
    C_INACTIVE  = "#16213e"
    C_ACTIVE    = Colors.BG_CARD
    C_HOVER     = Colors.BG_HOVER
    C_BORDER    = Colors.BORDER
    C_TEXT_ON   = Colors.TEXT_ON
    C_TEXT_OFF  = Colors.TEXT_OFF
    C_CLOSE     = Colors.ACCENT
    C_ADD       = Colors.GREEN
    C_ACCENT    = Colors.ACCENT
    C_DROP_LINE = Colors.ACCENT

    _all_tabbars: list[TabBar] = []

    def __init__(
        self,
        master: tk.Widget,
        on_detach: Callable | None = None,
        on_new_tab: Callable | None = None,
        on_receive: Callable | None = None,
        **kw,
    ) -> None:
        super().__init__(master, bg=self.C_BG, height=self.TAB_H, highlightthickness=0, **kw)
        self._tabs: list[dict] = []
        self._active: int | None = None
        self._hover_tab: int | None = None
        self._hover_close = False
        self._next_id = 0
        self.on_detach   = on_detach
        self.on_new_tab  = on_new_tab
        self.on_receive  = on_receive
        self._select_cbs: dict[int, Callable] = {}
        self._close_cbs:  dict[int, Callable] = {}

        # État du drag
        self._drag_tab:        int | None = None
        self._drag_x0         = 0
        self._drag_cx         = 0
        self._drag_moved      = False
        self._drag_ghost:     tk.Toplevel | None = None
        self._drag_insert_pos: int | None = None
        self._drag_outside    = False
        self._drag_over_bar:  TabBar | None = None

        self.bind("<Configure>",       lambda e: self._redraw())
        self.bind("<Motion>",          self._on_motion)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        TabBar._all_tabbars.append(self)
        self.bind("<Destroy>", lambda e: TabBar._all_tabbars.remove(self)
                  if self in TabBar._all_tabbars else None)

    # ── API publique ──────────────────────────────────────────────────────────

    def add_tab(self, label: str, select_cb: Callable | None = None, close_cb: Callable | None = None) -> int:
        """Ajoute un onglet à la fin et l'active."""
        tid = self._next_id; self._next_id += 1
        self._tabs.append({"id": tid, "label": label})
        if select_cb: self._select_cbs[tid] = select_cb
        if close_cb:  self._close_cbs[tid]  = close_cb
        self.set_active(tid)
        return tid

    def insert_tab(self, pos: int, label: str, select_cb: Callable | None = None, close_cb: Callable | None = None) -> int:
        """Insère un onglet à la position donnée et l'active."""
        tid = self._next_id; self._next_id += 1
        self._tabs.insert(pos, {"id": tid, "label": label})
        if select_cb: self._select_cbs[tid] = select_cb
        if close_cb:  self._close_cbs[tid]  = close_cb
        self.set_active(tid)
        return tid

    def remove_tab(self, tab_id: int) -> None:
        """Supprime un onglet et active le dernier restant."""
        self._tabs = [t for t in self._tabs if t["id"] != tab_id]
        self._select_cbs.pop(tab_id, None)
        self._close_cbs.pop(tab_id, None)
        if self._active == tab_id:
            self._active = self._tabs[-1]["id"] if self._tabs else None
            if self._active is not None:
                cb = self._select_cbs.get(self._active)
                if cb: cb()
        self._redraw()

    def set_active(self, tab_id: int) -> None:
        """Active l'onglet donné."""
        self._active = tab_id
        self._redraw()

    def rename_tab(self, tab_id: int, label: str) -> None:
        """Renomme un onglet."""
        for t in self._tabs:
            if t["id"] == tab_id:
                t["label"] = label
                break
        self._redraw()

    def tab_count(self) -> int:
        return len(self._tabs)

    def get_label(self, tab_id: int) -> str:
        for t in self._tabs:
            if t["id"] == tab_id:
                return t["label"]
        return "?"

    # ── Géométrie interne ─────────────────────────────────────────────────────

    def _tab_w(self) -> int:
        n = len(self._tabs)
        if n == 0:
            return self.TAB_MIN_W
        avail = max(0, self.winfo_width() - 50)
        return max(self.TAB_MIN_W, min(self.TAB_MAX_W, avail // n))

    def _tab_rects(self, exclude_id: int | None = None) -> dict[int, tuple | None]:
        w = self._tab_w()
        x = 2
        rects: dict[int, tuple | None] = {}
        for tab in self._tabs:
            if tab["id"] == exclude_id:
                rects[tab["id"]] = None
                x += w + 2
                continue
            rects[tab["id"]] = (x, 0, x + w, self.TAB_H)
            x += w + 2
        return rects

    def _plus_x(self) -> int:
        rects = self._tab_rects()
        vals  = [r[2] for r in rects.values() if r]
        return (max(vals) + 8) if vals else 6

    def _insert_pos_from_x(self, x: int) -> int:
        w = self._tab_w()
        n = len(self._tabs)
        return max(0, min(n, int((x - 2 + w // 2) // (w + 2))))

    # ── Dessin ────────────────────────────────────────────────────────────────

    def _redraw(self, drop_preview_pos: int | None = None) -> None:
        self.delete("all")
        W = self.winfo_width(); H = self.TAB_H
        self.create_rectangle(0, 0, W, H, fill=self.C_BG, outline="")
        self.create_line(0, H - 1, W, H - 1, fill=self.C_BORDER)
        w                = self._tab_w()
        is_reorder_drag  = (self._drag_tab is not None and not self._drag_outside)
        insert_pos       = self._drag_insert_pos
        dragged_i        = next(
            (i for i, t in enumerate(self._tabs) if t["id"] == self._drag_tab), None
        ) if is_reorder_drag else None
        by               = H // 2 + 1
        label_avail      = w - self.PAD_X * 2 - self.BTN_R * 2 - self.PAD_BTN - 4

        def _draw_tab(i, tab, is_dragged):
            tid        = tab["id"]
            is_active  = tid == self._active
            is_hover   = (tid == self._hover_tab and not self._drag_moved)

            if is_reorder_drag:
                if is_dragged:
                    # L'onglet en cours de drag suit TOUJOURS la souris
                    x1 = 2 + i * (w + 2) + self._drag_cx
                else:
                    # Les autres onglets ne se décalent que s'il y a un point d'insertion actif
                    slot = i
                    if insert_pos is not None and dragged_i is not None:
                        if dragged_i < insert_pos:
                            if dragged_i < i <= insert_pos:
                                slot = i - 1
                        else:
                            if insert_pos <= i < dragged_i:
                                slot = i + 1
                    x1 = 2 + slot * (w + 2)
            else:
                x1 = 2 + i * (w + 2)

            x2 = x1 + w
            bg = self.C_ACTIVE if is_active else (self.C_HOVER if is_hover else self.C_INACTIVE)
            self.create_rectangle(x1 + 1, 3, x2 - 1, H, fill=bg, outline=self.C_BORDER, width=1)
            if is_active:
                self.create_rectangle(x1 + 2, 2, x2 - 2, 5, fill=self.C_ACCENT, outline="")
            if is_dragged:
                self.create_rectangle(x1 + 1, 3, x2 - 1, H,
                                       fill="#2a1a3a", outline=self.C_ACCENT, width=2)
                # Légère ombre projetée pour l'onglet en survol
                self.create_line(x2, 4, x2, H, fill="#0F0F13", width=2)

            bx = x2 - self.PAD_BTN - self.BTN_R
            close_hover = (is_hover and self._hover_close and tid == self._hover_tab)
            if close_hover:
                self.create_oval(bx - self.BTN_R, by - self.BTN_R,
                                  bx + self.BTN_R, by + self.BTN_R,
                                  fill=self.C_CLOSE, outline="")
            self.create_text(bx, by, text="✕",
                             fill="#ffffff" if close_hover else "#3a4a6a",
                             font=("Arial", 9, "bold"))

            label = tab["label"]
            while len(label) > 3 and len(label) * 7 > label_avail:
                label = label[:-2] + "…"
            self.create_text(x1 + self.PAD_X, by, text=label, anchor="w",
                             fill=self.C_TEXT_ON if is_active else self.C_TEXT_OFF,
                             font=("Consolas", 10, "bold" if is_active else "normal"))

        # 1. Dessiner tous les onglets NORMAUX
        for i, tab in enumerate(self._tabs):
            is_dragged = (tab["id"] == self._drag_tab and is_reorder_drag)
            if not is_dragged:
                _draw_tab(i, tab, False)

        # 2. Dessiner l'onglet survolé (drag) AU-DESSUS des autres
        if is_reorder_drag and dragged_i is not None:
            _draw_tab(dragged_i, self._tabs[dragged_i], True)

        if is_reorder_drag and insert_pos is not None:
            lx = max(2, 2 + insert_pos * (w + 2) - 2)
            self.create_line(lx, 4, lx, H - 4,
                             fill=self.C_DROP_LINE, width=3, capstyle="round")

        if drop_preview_pos is not None:
            lx = max(2, 2 + drop_preview_pos * (w + 2) - 2)
            self.create_line(lx, 2, lx, H - 2, fill="#00ff88", width=3, capstyle="round")
            self.create_text(lx + 8, H // 2, text="⬇ Déposer ici", anchor="w",
                             fill="#00ff88", font=("Consolas", 9, "bold"))

        n = len(self._tabs)
        self.create_text(2 + n * (w + 2) + 18, H // 2 + 1, text="+",
                         fill=self.C_ADD, font=("Arial", 17, "bold"))

    # ── Hit-testing ───────────────────────────────────────────────────────────

    def _hit(self, x: int, y: int) -> tuple[int | str | None, bool]:
        w = self._tab_w()
        for i, tab in enumerate(self._tabs):
            tid = tab["id"]
            x1  = 2 + i * (w + 2)
            x2  = x1 + w
            if x1 <= x <= x2:
                bx = x2 - self.PAD_BTN - self.BTN_R
                if abs(x - bx) <= self.BTN_R + 3:
                    return tid, True
                return tid, False
        px = self._plus_x()
        if px <= x <= px + 26:
            return "NEW", False
        return None, False

    @classmethod
    def _find_tabbar_under(cls, x_root: int, y_root: int, exclude: TabBar | None = None) -> TabBar | None:
        for tb in cls._all_tabbars:
            if tb is exclude:
                continue
            if not tb.winfo_exists():
                continue
            try:
                tx = tb.winfo_rootx(); ty = tb.winfo_rooty()
                tw = tb.winfo_width(); th = tb.winfo_height()
                if tx <= x_root <= tx + tw and ty <= y_root <= ty + th:
                    return tb
            except Exception:
                continue
        return None

    # ── Événements souris ─────────────────────────────────────────────────────

    def _on_motion(self, event: tk.Event) -> None:
        tid, is_close = self._hit(event.x, event.y)
        changed = (tid != self._hover_tab or is_close != self._hover_close)
        self._hover_tab   = tid if tid != "NEW" else None
        self._hover_close = is_close
        if changed:
            self._redraw()

    def _on_leave(self, event: tk.Event | None = None) -> None:
        self._hover_tab = None
        self._hover_close = False
        self._redraw()

    def _on_press(self, event: tk.Event) -> None:
        tid, is_close = self._hit(event.x, event.y)
        if tid == "NEW":
            if self.on_new_tab:
                self.on_new_tab()
            return
        if tid is None:
            return
        if is_close:
            cb = self._close_cbs.get(tid)
            if cb:
                cb()
            return
        if tid != self._active:
            self._active = tid
            cb = self._select_cbs.get(tid)
            if cb:
                cb()
            self._redraw()
        self._drag_tab        = tid
        self._drag_x0         = event.x
        self._drag_cx         = 0
        self._drag_moved      = False
        self._drag_outside    = False
        self._drag_insert_pos = None
        self._drag_over_bar   = None

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_tab is None:
            return
        self._drag_cx    = event.x - self._drag_x0
        self._drag_moved = abs(self._drag_cx) > 4
        ax = event.x_root
        ay = event.y_root
        my_x1 = self.winfo_rootx(); my_y1 = self.winfo_rooty()
        my_x2 = my_x1 + self.winfo_width()
        my_y2 = my_y1 + self.winfo_height()
        on_self    = (my_x1 <= ax <= my_x2 and my_y1 <= ay <= my_y2)
        target_bar = None if on_self else TabBar._find_tabbar_under(ax, ay, exclude=self)
        wants_ghost = not on_self

        if wants_ghost and self._drag_ghost is None:
            self._drag_outside = True
            self._drag_ghost   = tk.Toplevel(self)
            self._drag_ghost.overrideredirect(True)
            self._drag_ghost.attributes("-alpha", 0.60)
            self._drag_ghost.attributes("-topmost", True)
            self._drag_ghost.configure(bg=self.C_ACCENT)
            tk.Label(self._drag_ghost,
                     text=f"  📄  {self.get_label(self._drag_tab)}  ",
                     bg=self.C_ACCENT, fg="#ffffff",
                     font=("Consolas", 12, "bold"), padx=14, pady=10).pack()
        elif not wants_ghost and self._drag_ghost is not None:
            self._drag_outside = False
            self._drag_ghost.destroy()
            self._drag_ghost = None

        if self._drag_ghost:
            self._drag_ghost.geometry(f"+{ax - 80}+{ay - 20}")

        if self._drag_over_bar is not None and self._drag_over_bar is not target_bar:
            self._drag_over_bar._redraw()

        self._drag_over_bar = target_bar

        if target_bar is not None:
            local_x = ax - target_bar.winfo_rootx()
            preview = target_bar._insert_pos_from_x(local_x)
            target_bar._redraw(drop_preview_pos=preview)
            self._drag_insert_pos = None
            self._redraw()
            return

        if on_self and self._drag_moved:
            self._drag_insert_pos = self._insert_pos_from_x(event.x)
            dragged_i = next(
                (i for i, t in enumerate(self._tabs) if t["id"] == self._drag_tab), None
            )
            if dragged_i is not None and self._drag_insert_pos in (dragged_i, dragged_i + 1):
                self._drag_insert_pos = None
        else:
            self._drag_insert_pos = None
        self._redraw()

    def _on_release(self, event: tk.Event) -> None:
        if self._drag_tab is None:
            return
        ax  = event.x_root
        ay  = event.y_root
        tid = self._drag_tab
        if self._drag_ghost:
            self._drag_ghost.destroy()
            self._drag_ghost = None
        self.update_idletasks()
        if self._drag_over_bar is not None:
            self._drag_over_bar._redraw()

        my_x1 = self.winfo_rootx(); my_y1 = self.winfo_rooty()
        my_x2 = my_x1 + self.winfo_width()
        my_y2 = my_y1 + self.winfo_height()
        on_self    = (my_x1 <= ax <= my_x2 and my_y1 <= ay <= my_y2)
        target_bar = None if on_self else TabBar._find_tabbar_under(ax, ay, exclude=self)

        if target_bar is not None and self.on_detach:
            local_x    = ax - target_bar.winfo_rootx()
            insert_pos = target_bar._insert_pos_from_x(local_x)
            self._reset_drag()
            self.on_detach(tid, ax, ay, target_bar=target_bar, insert_pos=insert_pos)
            return

        if self._drag_outside and not on_self and self.on_detach and len(self._tabs) > 1:
            self._reset_drag()
            self.on_detach(tid, ax, ay)
            return

        if self._drag_moved and self._drag_insert_pos is not None:
            dragged_i = next(
                (i for i, t in enumerate(self._tabs) if t["id"] == self._drag_tab), None
            )
            if dragged_i is not None:
                insert = self._drag_insert_pos
                if insert > dragged_i:
                    insert -= 1
                if insert != dragged_i:
                    tab = self._tabs.pop(dragged_i)
                    self._tabs.insert(insert, tab)
                    win_host = self.winfo_toplevel()
                    if hasattr(win_host, '_sync_tab_order'):
                        win_host._sync_tab_order([t["id"] for t in self._tabs])
        self._reset_drag()

    def _reset_drag(self) -> None:
        self._drag_tab        = None
        self._drag_cx         = 0
        self._drag_moved      = False
        self._drag_outside    = False
        self._drag_insert_pos = None
        self._drag_over_bar   = None
        self._redraw()
