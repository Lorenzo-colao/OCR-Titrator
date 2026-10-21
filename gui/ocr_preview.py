from __future__ import annotations

import re
import math
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import Any

from PIL import Image, ImageTk, ImageDraw
import pandas as pd

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from gui.theme import Colors, Fonts
from config    import CFG, COLONNES
from core.excel_export import validate_dataframe_for_export

class OCRPreviewWindow(tk.Toplevel):
    """Fenêtre de vérification OCR interactive."""

    def __init__(
        self,
        master,
        df: pd.DataFrame,
        pdf_path: str,
        word_boxes: list[list[tuple[str, int, int, int, int]]],
        pages: list[Any],
        out_path: str = None,
        **kw,
    ) -> None:
        super().__init__(master, **kw)
        self.title(f"🔍  Vérification OCR — {pdf_path.replace('\\\\', '/').split('/')[-1]}")
        self.geometry("1100x680"); self.minsize(800, 480)
        self.configure(bg=Colors.BG_DARK)
        self.resizable(True, True)

        try:
            import os, sys
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
                   else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
            ico = os.path.join(base, "icon.ico")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        self._raw_df     = df.reset_index(drop=True)
        self._df         = None
        self._col_stats  = None
        self._n_flags    = 0
        self._word_boxes = word_boxes   # list[page] → list[(txt, left, top, w, h)]
        self._pages      = pages        # list[PIL.Image] (images prétraitées)
        self._zoom_win   = None
        self._out_path   = out_path

        # Pré-calculer les coordonnées X/Y
        self._data_rows   = self._build_data_rows()
        self._col_centers = self._build_col_centers()
        self._row_mapping = self._map_df_to_data_rows()

        self._refresh_validation()
        self._build_ui()
        self.update_idletasks()
        mx = master.winfo_rootx() + (master.winfo_width()  - self.winfo_width())  // 2
        my = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{mx}+{my}")
        self.lift(); self.focus_force()

    def _refresh_validation(self):
        """Réapplique les règles de validation et de cohérence."""
        self._df, self._col_stats, self._n_flags = validate_dataframe_for_export(self._raw_df)

    def _save_and_close(self):
        """Exporte vers excel_export (avec le df modifié) et quitte."""
        if not self._out_path:
            self.destroy()
            return
            
        try:
            from core.excel_export import export_excel_with_flags
            # export_excel_with_flags re-validera mais ça ne pose pas de problème
            export_excel_with_flags(self._raw_df, self._out_path)
            messagebox.showinfo("Succès", f"Fichier Excel mis à jour.\n{self._out_path}", parent=self)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur de sauvegarde :\n{e}", parent=self)

    # ── Précalcul des lignes de données ──────────────────────────────────────

    def _build_data_rows(self) -> list[tuple[int, list[tuple[str, int, int, int, int]]]]:
        NUM_RE = re.compile(r'\d|NaN', re.IGNORECASE)
        result = []

        for pg_idx, boxes in enumerate(self._word_boxes):
            if not boxes:
                continue

            lines: list[list] = []
            for item in sorted(boxes, key=lambda b: b[2]):
                placed = False
                for line in lines:
                    if abs(item[2] - line[0][2]) < 12:
                        line.append(item)
                        placed = True
                        break
                if not placed:
                    lines.append([item])

            for line in lines:
                nums = [b for b in line if NUM_RE.search(b[0].strip())]
                if len(nums) >= 1:
                    nums.sort(key=lambda b: b[1])
                    result.append((pg_idx, nums))

        return result

    def _build_col_centers(self) -> list[float]:
        nb_cols = len(COLONNES)
        sums  = [0.0] * nb_cols
        count = [0]   * nb_cols

        for pg, tokens in self._data_rows:
            if len(tokens) == nb_cols:
                for j, t in enumerate(tokens):
                    sums[j] += (t[1] + t[3] / 2.0)
                    count[j] += 1

        centers = []
        for s, c in zip(sums, count):
            if c > 0:
                centers.append(s / c)
            else:
                centers.append(0.0)

        if centers[0] == 0.0 and count == [0]*nb_cols:
            centers = [100.0 + i*80.0 for i in range(nb_cols)]

        return centers

    def _map_df_to_data_rows(self) -> dict[int, int]:
        """Associe chaque ligne du DataFrame à l'indice dans _data_rows par similarité."""
        mapping = {}
        last_match = -1
        
        for i, row in self._raw_df.iterrows():
            best_idx = -1
            max_score = -1
            
            # Recherche stricte vers l'avant : on ne map JAMAIS deux lignes sur le même _data_rows
            search_start = last_match + 1
            search_end = min(search_start + 10, len(self._data_rows))
            
            for idx in range(search_start, search_end):
                pg, tokens = self._data_rows[idx]
                score = 0
                tok_vals = []
                for t in tokens:
                    try:
                        s = re.sub(r'[^\d.,+-]', '', t[0]).replace(',', '.')
                        if s: tok_vals.append(float(s))
                    except: pass
                
                matched_ti = set()
                for cv in row.values:
                    if pd.isna(cv): continue
                    for ti, tv in enumerate(tok_vals):
                        if ti in matched_ti: continue
                        if abs(float(cv) - tv) < 1e-4:
                            score += 1
                            matched_ti.add(ti)
                            break
                            
                if score > max_score:
                    max_score = score
                    best_idx = idx
            
            if max_score > 0:
                mapping[i] = best_idx
                last_match = best_idx
            else:
                # Fallback brutal : on avance d'une ligne quoiqu'il arrive
                # pour ne pas rester coincés ni sauter trop
                mapping[i] = search_start if search_start < len(self._data_rows) else max(0, len(self._data_rows) - 1)
                if mapping[i] >= search_start:
                    last_match = search_start
        return mapping

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        hdr = tk.Frame(self, bg=Colors.BG_PANEL, height=56)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr,
                 text="🔍  Double-clic = Zoom PDF  |  Clic-Droit = Modifier valeur",
                 font=Fonts.SANS_LG, bg=Colors.BG_PANEL, fg=Colors.TEXT_OFF
                 ).pack(side="left", padx=20, pady=14)
        tk.Label(hdr, text=f"{len(self._df)} lignes",
                 font=Fonts.SANS_SM, bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED
                 ).pack(side="right", padx=20)

        tk.Frame(self, bg=Colors.BORDER, height=1).pack(fill="x")

        body = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=Colors.BG_DARK, borderwidth=0, sashwidth=6, sashcursor="sb_h_double_arrow")
        body.pack(fill="both", expand=True, padx=16, pady=14)

        table_container = tk.Frame(body, bg=Colors.BG_DARK)
        table_container.pack_propagate(False) # Empêche le contenu de forcer la taille
        body.add(table_container, minsize=300, stretch="always")

        self._vsb = tk.Scrollbar(table_container)
        self._vsb.pack(side="right", fill="y")
        
        self._tbl = tk.Frame(table_container, bg=Colors.BG_DARK)
        self._tbl.pack(fill="both", expand=True)

        self._max_rows = 50
        self._current_top = 0
        
        # Maintien de l'échelle des panneaux lors du redimensionnement (Plein Écran)
        self._sash_ratio = 0.55
        def _on_body_resize(e):
            if e.widget == body and e.width > 100:
                try: body.sash_place(0, int(e.width * self._sash_ratio), 0)
                except Exception: pass
        body.bind("<Configure>", _on_body_resize)

        def _on_sash_drag(e):
            if e.widget == body and body.winfo_width() > 100:
                try: self._sash_ratio = body.sash_coord(0)[0] / body.winfo_width()
                except Exception: pass
        body.bind("<ButtonRelease-1>", _on_sash_drag)

        # Cadre du graphique visuel
        if HAS_MATPLOTLIB:
            self._plot_frame = tk.Frame(body, bg=Colors.BG_PANEL)
            self._plot_frame.pack_propagate(False) # Matplotlib ne doit PAS dépasser sur le tableau
            body.add(self._plot_frame, minsize=250, stretch="always")
            
            # Plus petit initialement pour qu'il s'écrase sans résister, puis expand=True fera le reste
            self._figure = Figure(figsize=(2, 2), dpi=100)
            self._figure.patch.set_facecolor(Colors.BG_PANEL)
            self._ax = self._figure.add_subplot(111)
            self._ax.set_facecolor(Colors.BG_DARK)
            
            self._canvas_plot = FigureCanvasTkAgg(self._figure, master=self._plot_frame)
            self._canvas_plot.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)
            
            def on_hover(event):
                if event.inaxes == self._ax and getattr(self, '_line_plot', None):
                    cont, ind = self._line_plot.contains(event)
                    if cont:
                        idx = ind["ind"][0]
                        if hasattr(self, '_s_data_index') and idx < len(self._s_data_index):
                            real_idx = self._s_data_index[idx]
                            val = self._s_data_values[idx]
                            self._hovered_idx = real_idx
                            
                            self._annot.xy = (real_idx + 1, val)
                            self._annot.set_text(f" Ligne {real_idx+1} \n {val:g} ")
                            self._annot.set_visible(True)
                            self._canvas_plot.draw_idle()
                            return
                if getattr(self, '_annot', None) and self._annot.get_visible():
                    self._annot.set_visible(False)
                    self._hovered_idx = None
                    self._canvas_plot.draw_idle()

            def on_click(event):
                if getattr(self, "_hovered_idx", None) is not None:
                    target_idx = self._hovered_idx
                    # Lookup direct dans l'index du DataFrame (O(1) au lieu de O(n))
                    df_indices = list(self._df.index)
                    vi = None
                    if target_idx in df_indices:
                        vi = df_indices.index(target_idx)
                    if vi is not None:
                        # Scroll to make it visible
                        limit = min(self._max_rows, len(self._df))
                        nt = max(0, min(max(0, vi - 4), len(self._df) - limit))
                        if nt != self._current_top:
                            self._current_top = nt
                            self._fill_table(update_plot=False)
                        
                        rel_i = vi - self._current_top
                        
                        # Mettre en évidence visuellement la ligne
                        if hasattr(self, '_cells') and 0 <= rel_i < self._max_rows:
                            for j in range(len(COLONNES)):
                                if (rel_i, j) in self._cells:
                                    c = self._cells[(rel_i, j)]
                                    c.configure(bg=Colors.GREEN, fg=Colors.BG_DARK)
                                    # Remettre la couleur après 800 ms
                                    self.after(800, lambda cell=c: cell.configure(bg=getattr(cell, "_orig_bg", Colors.BG_CARD), fg=Colors.TEXT_ON))

            def on_scroll(event):
                if event.inaxes != self._ax: return
                if event.key not in ('control', 'ctrl'): return
                
                base_scale = 1.3
                if event.button == 'up':
                    scale_factor = 1 / base_scale
                elif event.button == 'down':
                    scale_factor = base_scale
                else:
                    return

                xdata = event.xdata
                ydata = event.ydata
                
                cur_xlim = self._ax.get_xlim()
                cur_ylim = self._ax.get_ylim()
                
                new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
                new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
                
                relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
                rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
                
                self._ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
                self._ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
                
                self._canvas_plot.draw_idle()
                        
            self._canvas_plot.mpl_connect("motion_notify_event", on_hover)
            self._canvas_plot.mpl_connect("button_press_event", on_click)
            self._canvas_plot.mpl_connect("scroll_event", on_scroll)
            
            # Ajouter le bouton Reset Zoom
            def _reset_zoom():
                if hasattr(self, '_ax_orig_xlim') and hasattr(self, '_ax_orig_ylim'):
                    self._ax.set_xlim(self._ax_orig_xlim)
                    self._ax.set_ylim(self._ax_orig_ylim)
                    self._canvas_plot.draw_idle()
                    
            btn_reset = tk.Button(self._plot_frame, text="⟲ Reset Zoom", bg=Colors.BG_CARD, fg=Colors.TEXT_ON,
                                  relief="flat", cursor="hand2", font=Fonts.SANS_SM, command=_reset_zoom)
            btn_reset.place(relx=0.98, rely=0.02, anchor="ne")
        else:
            self._ax = None

        self._fill_table()

        tk.Frame(self, bg=Colors.BORDER, height=1).pack(fill="x")
        foot = tk.Frame(self, bg=Colors.BG_PANEL, height=56); foot.pack(fill="x")
        foot.pack_propagate(False)
        
        self.btn_save = tk.Button(foot, text="💾  Valider et Exporter", command=self._save_and_close,
                  bg=Colors.ACCENT, fg=Colors.TEXT_ON,
                  relief="flat", font=Fonts.SANS_LG_B, padx=20, cursor="hand2")
        self.btn_save.pack(side="right", padx=16, pady=10)
        
        tk.Button(foot, text="✕  Annuler", command=self.destroy,
                  bg=Colors.BG_CARD_ALT, fg=Colors.TEXT_OFF,
                  relief="flat", font=Fonts.SANS_LG, padx=12, cursor="hand2"
                  ).pack(side="right", padx=8, pady=10)

    def _build_table_widgets(self) -> None:
        """Construit les labels en mode Virtual Scrolling (50 lignes max) pour FIXER L'AFFICHAGE ET LES GROS FICHIERS."""
        for widget in self._tbl.winfo_children(): widget.destroy()
        
        f = self._tbl
        cols = list(COLONNES)
        self._cells = {}

        tk.Label(f, text="#", font=Fonts.SANS_LG_B, bg=Colors.BG_PANEL, fg=Colors.TEXT_MUTED,
                 width=5, anchor="center", pady=8).grid(row=0, column=0, padx=1, pady=1)
        for j, col in enumerate(cols):
            tk.Label(f, text=col, font=Fonts.SANS_LG_B, bg=Colors.BG_PANEL, fg=Colors.TEXT_ON,
                     width=12, anchor="center", pady=8).grid(row=0, column=j + 1, padx=1, pady=1, sticky="nsew")

        real_indices = list(self._df.index)
        limit = min(self._max_rows, len(self._df))
        
        for i in range(limit):
            row_bg = Colors.BG_CARD if i % 2 == 0 else Colors.BG_CARD_ALT
            lbl_idx = tk.Label(f, text=str(i + 1), font=Fonts.MONO_SM, bg=row_bg, fg=Colors.TEXT_MUTED,
                     width=5, anchor="center", pady=6)
            lbl_idx.grid(row=i + 1, column=0, padx=1, pady=1)
            self._cells[(i, -1)] = lbl_idx

            for j, col in enumerate(cols):
                cell = tk.Label(f, font=Fonts.MONO_LG, width=12, anchor="center", pady=6, cursor="hand2")
                cell.grid(row=i + 1, column=j + 1, padx=1, pady=1, sticky="nsew")

                def on_enter(e, c=cell): c.configure(bg=Colors.ACCENT)
                def on_leave(e, c=cell): c.configure(bg=getattr(c, "_orig_bg", Colors.BG_CARD))
                def on_dbl(e, ri=i, ci=j): 
                    true_i = self._current_top + ri
                    if true_i < len(self._df):
                        self._on_dblclick(self._cells[(ri, ci)].cget("text"), real_indices[true_i], ci)
                def on_rclick(e, ri=i, ci=j, ccol=col, c=cell): 
                    true_i = self._current_top + ri
                    if true_i < len(self._df):
                        self._start_inline_edit(c, real_indices[true_i], ccol, c.cget("text"))
                
                cell.bind("<Enter>", on_enter)
                cell.bind("<Leave>", on_leave)
                cell.bind("<Double-1>", on_dbl)
                cell.bind("<Button-3>", on_rclick)
                
                self._cells[(i, j)] = cell

        def _do_scroll(delta):
            n = self._current_top - delta
            n = max(0, min(n, len(self._df) - limit))
            if n != self._current_top:
                self._current_top = n
                self._fill_table(update_plot=False)

        def _mouse_wheel(e): _do_scroll(int(e.delta / 120))
        self._tbl.bind("<MouseWheel>", _mouse_wheel)
        for child in self._tbl.winfo_children(): child.bind("<MouseWheel>", _mouse_wheel)
        
        def _sb_command(*args):
            if args[0] == "moveto":
                frac = float(args[1])
                nt = int(frac * (len(self._df) - limit))
            elif args[0] == "scroll":
                nt = self._current_top + int(args[1])
            else: return
            nt = max(0, min(nt, len(self._df) - limit))
            if nt != self._current_top:
                self._current_top = nt
                self._fill_table(update_plot=False)
                
        self._vsb.config(command=_sb_command)

    def _fill_table(self, update_plot=True) -> None:
        if not hasattr(self, "_cells"):
            self._build_table_widgets()

        cols = list(COLONNES)
        RED_FILL     = "#C0392B"
        ORANGE_FILL  = "#E67E22"
        YELLOW_FILL  = "#F39C12"
        BLUE_FILL    = "#2471A3"

        limit = min(self._max_rows, len(self._df))
        if len(self._df) <= limit:
            self._vsb.set(0.0, 1.0)
        else:
            self._vsb.set(self._current_top / max(1, len(self._df)), 
                          (self._current_top + limit) / max(1, len(self._df)))

        for i in range(limit):
            true_i = self._current_top + i
            if true_i >= len(self._df): break
            
            idx = self._df.index[true_i]
            row = self._df.loc[idx]

            row_bg = Colors.BG_CARD if true_i % 2 == 0 else Colors.BG_CARD_ALT
            has_flag   = bool(row.get("Flag", ""))
            is_fix_row = has_flag and "corrigé" in str(row.get("Flag", ""))

            self._cells[(i, -1)].configure(text=str(true_i + 1), bg=row_bg)

            for j, col in enumerate(cols):
                val = row[col]
                bg, fg = row_bg, Colors.TEXT_ON
                
                if pd.isna(val):
                    txt = "NaN"
                    if has_flag and not is_fix_row: bg = ORANGE_FILL
                else:
                    txt = f"{val:g}"
                    if col == "mL2" and row.get("Fix_mL2", ""):
                        bg = BLUE_FILL
                    elif col == "delta" and row.get("Fix_delta", ""):
                        bg = BLUE_FILL
                    elif has_flag and not is_fix_row:
                        v_rules = CFG.validation_rules.get(col)
                        if v_rules and (val < v_rules["min"] or val > v_rules["max"]):
                            bg = RED_FILL
                        elif getattr(self, '_col_stats', None) and col in self._col_stats:
                            lo, hi = self._col_stats[col]
                            if val < lo or val > hi: bg = YELLOW_FILL

                cell = self._cells[(i, j)]
                cell.configure(text=txt, bg=bg, fg=fg)
                cell._orig_bg = bg

        if update_plot:
            self._draw_plot()

    def _draw_plot(self) -> None:
        """Trace la courbe de dynamique (mL1) sur le côté droit pour repérer les erreurs visuellement."""
        if getattr(self, '_ax', None) is None: return
            
        self._ax.clear()
        
        self._annot = self._ax.annotate("", xy=(0,0), xytext=(10,10), textcoords="offset points",
                                        bbox=dict(boxstyle="round4", fc=Colors.BG_CARD_ALT, ec=Colors.BORDER, alpha=0.9),
                                        color=Colors.TEXT_ON, fontsize=9)
        self._annot.set_visible(False)
        self._hovered_idx = None
        
        self._ax.set_facecolor(Colors.BG_DARK)
        self._ax.tick_params(colors=Colors.TEXT_MUTED, labelsize=8)
        for spine in self._ax.spines.values(): spine.set_color(Colors.BORDER)
            
        y_col = COLONNES[0] if len(COLONNES) > 0 else 'mL'
        
        if y_col in self._df.columns:
            s_data = self._df[y_col].dropna()
            
            if not s_data.empty:
                self._s_data_index = s_data.index
                self._s_data_values = s_data.values
                self._line_plot, = self._ax.plot(s_data.index + 1, s_data.values, marker='o', 
                              linestyle='-', color=Colors.ACCENT, markersize=5, linewidth=1.5, picker=5)
                
                flagged_idx = self._df[self._df['Flag'].notna() & (self._df['Flag'] != "")].index
                valid_flag_idx = flagged_idx.intersection(s_data.index)
                if not valid_flag_idx.empty:
                    self._ax.plot(valid_flag_idx + 1, s_data.loc[valid_flag_idx], 
                                  marker='x', linestyle='', color="#EF4444", markersize=8, markeredgewidth=2)

        self._ax.set_title(f"Évolution de {y_col} (détection d'anomalies)", color=Colors.TEXT_ON, fontsize=10, pad=10)
        self._ax.set_xlabel("N° Ligne (Temps)", color=Colors.TEXT_OFF, fontsize=9)
        self._ax.set_ylabel(y_col, color=Colors.TEXT_OFF, fontsize=9)
        self._figure.tight_layout()
        
        self._ax_orig_xlim = self._ax.get_xlim()
        self._ax_orig_ylim = self._ax.get_ylim()
        
        self._canvas_plot.draw_idle()

    def _start_inline_edit(self, cell: tk.Label, row_idx: int, col_name: str, current_val: str) -> None:
        """Remplace temporairement le label par un champ de texte pour édition."""
        entry = tk.Entry(cell, font=Fonts.MONO_LG, bg=Colors.BG_CARD_ALT, fg=Colors.TEXT_ON, justify="center")
        entry.insert(0, current_val)
        entry.place(relx=0, rely=0, relwidth=1, relheight=1)
        entry.focus_set()
        entry.select_range(0, "end")
        
        # Un flag pour s'assurer qu'on ne commit pas deux fois (Return + FocusOut)
        _committed = [False]

        def commit(e=None):
            if _committed[0]:
                return
            _committed[0] = True
            
            new_val = entry.get().strip().replace(',', '.')
            entry.destroy()
            if new_val == current_val:
                return
            if new_val == "" or new_val.lower() == "nan":
                self._raw_df.at[row_idx, col_name] = pd.NA
            else:
                try:
                    self._raw_df.at[row_idx, col_name] = float(new_val)
                except ValueError:
                    messagebox.showerror("Erreur", "Valeur numérique invalide.", parent=self)
                    return
            
            # Recalculer validation
            self._refresh_validation()
            self._fill_table()
            
        def cancel(e=None):
            if not _committed[0]:
                _committed[0] = True
                entry.destroy()
            
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _on_dblclick(self, value: str, row_idx: int, col_idx: int) -> None:
        """Affiche le PDF pour la cellule cliquée."""
        if not self._pages or not self._data_rows:
            messagebox.showinfo("Indisponible", f"Impossible d'afficher l'image (Pages: {len(self._pages)}, DataRows: {len(self._data_rows)})", parent=self)
            return

        target_row = self._row_mapping.get(row_idx, row_idx % len(self._data_rows) if len(self._data_rows) else 0)
        
        if target_row >= len(self._data_rows):
            target_row = len(self._data_rows) - 1
            
        pg_idx, tokens = self._data_rows[target_row]

        expected_x = self._col_centers[col_idx] if col_idx < len(self._col_centers) else 0

        best_tok = None
        min_dist = float('inf')

        for tok in tokens:
            cx = tok[1] + tok[3] / 2.0
            dist = abs(cx - expected_x)
            if dist < min_dist:
                min_dist = dist
                best_tok = tok

        if best_tok and min_dist < 120:
            _t, l, t, w, h = best_tok
        else:
            l = int(expected_x - 30)
            t = tokens[0][2] if tokens else 0
            w = 60
            h = tokens[0][4] if tokens else 25

        self._show_zoom(pg_idx, l, t, w, h, value, row_idx, col_idx)

    def _show_zoom(self, pg_idx: int, l: int, t: int, w: int, h: int,
                   value: str, row_idx: int, col_idx: int) -> None:
        if self._zoom_win and self._zoom_win.winfo_exists():
            self._zoom_win.destroy()

        if pg_idx >= len(self._pages):
            return

        src = self._pages[pg_idx]
        
        # On garde la page entière pour pouvoir dézoomer au maximum
        crop = src.copy().convert("RGB")

        draw = ImageDraw.Draw(crop)
        bx1  = l;  by1 = t
        bx2  = bx1 + w; by2 = by1 + h
        for d in range(5):
            draw.rectangle([bx1 - d, by1 - d, bx2 + d, by2 + d], outline="#EF4444")

        # Résolution initiale x2
        zoomed = crop.resize((crop.width * 2, crop.height * 2), Image.BILINEAR)

        win = tk.Toplevel(self)
        col_name = list(COLONNES)[col_idx] if col_idx < len(COLONNES) else f"col{col_idx}"
        win.title(f"🔎  {col_name} = {value}  (ligne {row_idx+1} / page {pg_idx+1})")
        win.geometry("900x600")
        win.configure(bg=Colors.BG_DARK); win.resizable(True, True)
        self._zoom_win = win

        hdr = tk.Frame(win, bg=Colors.BG_PANEL, height=40)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr,
                 text=f"  Colonne : {col_name}  •  Valeur : {value}  •  Ligne {row_idx+1}  •  Page {pg_idx+1}  •  (Glissez avec la souris ou utilisez les barres)",
                 font=Fonts.SANS_LG_B, bg=Colors.BG_PANEL, fg=Colors.ACCENT
                 ).pack(side="left", padx=14, pady=8)

        frame_cv = tk.Frame(win, bg=Colors.BG_DARK)
        frame_cv.pack(fill="both", expand=True, padx=14, pady=12)

        vsb = tk.Scrollbar(frame_cv)
        vsb.pack(side="right", fill="y")
        hsb = tk.Scrollbar(frame_cv, orient="horizontal")
        hsb.pack(side="bottom", fill="x")

        cv = tk.Canvas(frame_cv, bg=Colors.BG_DARK, highlightthickness=0,
                       yscrollcommand=vsb.set, xscrollcommand=hsb.set, cursor="fleur")
        cv.pack(fill="both", expand=True)
        vsb.config(command=cv.yview)
        hsb.config(command=cv.xview)

        tk_img = ImageTk.PhotoImage(zoomed)
        img_id = cv.create_image(0, 0, image=tk_img, anchor="nw")
        cv.image = tk_img
        cv.configure(scrollregion=(0, 0, zoomed.width, zoomed.height))

        # Centrer sur le token
        current_z = [2.0]

        def _center_view(event=None):
            cw = cv.winfo_width()
            ch = cv.winfo_height()
            if cw > 1 and ch > 1:
                z = current_z[0]
                total_w = crop.width * z
                total_h = crop.height * z
                fx = ((bx1 + w / 2) * z - cw / 2) / total_w
                fy = ((by1 + h / 2) * z - ch / 2) / total_h
                cv.xview_moveto(max(0.0, min(1.0, fx)))
                cv.yview_moveto(max(0.0, min(1.0, fy)))
                if event: cv.unbind("<Configure>")

        def _do_zoom(e):
            old_z = current_z[0]
            # Zoom proportionnel (fluide) : 15% par cran
            factor = 1.15 if e.delta > 0 else (1.0 / 1.15)
            current_z[0] = max(0.1, min(6.0, current_z[0] * factor))
            
            if old_z == current_z[0]: return

            z = current_z[0]
            # Garder le centre visuel
            cw = cv.winfo_width()
            ch = cv.winfo_height()
            
            # Position relative du centre actuel avant zoom
            fx = cv.xview()[0] + (cw / 2) / (crop.width * old_z) if (crop.width * old_z) > 0 else 0
            fy = cv.yview()[0] + (ch / 2) / (crop.height * old_z) if (crop.height * old_z) > 0 else 0

            new_w, new_h = int(crop.width * z), int(crop.height * z)
            # Image.BILINEAR est bien plus rapide que LANCZOS pour la fluidité en temps réel
            new_img = ImageTk.PhotoImage(crop.resize((new_w, new_h), Image.BILINEAR))
            
            cv.itemconfig(img_id, image=new_img)
            cv.image = new_img
            cv.configure(scrollregion=(0, 0, new_w, new_h))

            # Repositionner le centre
            new_fx = fx - (cw / 2) / new_w if new_w > 0 else 0
            new_fy = fy - (ch / 2) / new_h if new_h > 0 else 0
            cv.xview_moveto(max(0.0, min(1.0, new_fx)))
            cv.yview_moveto(max(0.0, min(1.0, new_fy)))

        cv.bind("<Configure>", _center_view)
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-int(e.delta / 120), "units"))
        cv.bind("<Alt-MouseWheel>", _do_zoom)
        cv.bind("<Control-MouseWheel>", _do_zoom)
        cv.bind("<ButtonPress-1>", lambda e: cv.scan_mark(e.x, e.y))
        cv.bind("<B1-Motion>", lambda e: cv.scan_dragto(e.x, e.y, gain=1))

        tk.Button(win, text="Fermer  (Échap)", command=win.destroy,
                  bg=Colors.BG_CARD_ALT, fg=Colors.TEXT_OFF,
                  relief="flat", font=Fonts.SANS_LG, padx=10, cursor="hand2"
                  ).pack(pady=(0, 10))
        win.bind("<Escape>", lambda e: win.destroy())
        win.lift(); win.focus_force()
