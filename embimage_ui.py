"""Interface numerada do EmbImage, sem alterar o processamento das imagens."""
from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

BG = '#F4F4F8'
WHITE = '#FFFFFF'
INK = '#25253B'
MUTED = '#75758A'
ACCENT = '#6655CB'
TINT = '#EEEBFA'
LINE = '#E6E5EE'
STAGE = '#F8F8FB'


def color_hex(color):
    return '#%02x%02x%02x' % tuple(color)


class Surface(tk.Canvas):
    """Painel com borda e cantos antisserrilhados; o conteúdo continua sendo Tk."""
    def __init__(self, parent, scale, padding=20):
        super().__init__(parent, bg=parent.cget('bg'), highlightthickness=0, bd=0, width=1, height=1)
        self.scale, self.padding = scale, round(padding * scale)
        self.content = tk.Frame(self, bg=WHITE)
        self.window = self.create_window(0, 0, window=self.content, anchor='nw')
        self.bind('<Configure>', self._draw)
        self._photo = None

    def _draw(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 2 or height < 2:
            return
        image = Image.new('RGB', (width * 2, height * 2), self.cget('bg'))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, width * 2 - 2, height * 2 - 2), radius=round(38 * self.scale),
                               fill=WHITE, outline=LINE, width=2)
        self._photo = ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS), master=self)
        self.delete('surface')
        self.create_image(0, 0, anchor='nw', image=self._photo, tags='surface')
        self.tag_lower('surface')
        self.coords(self.window, self.padding, self.padding)
        self.itemconfigure(self.window, width=max(1, width - self.padding * 2),
                           height=max(1, height - self.padding * 2))


class Button(tk.Canvas):
    """Botão arredondado com foco de teclado, hover e estado desativado."""
    def __init__(self, parent, scale, text='', command=None, *, primary=False, number=None,
                 width=160, height=40, state='normal', swatch=None, target=None):
        self.scale, self.text, self.command = scale, text, command
        self.primary, self.number, self._state = primary, number, state
        self.swatch, self.target = swatch, target
        self.hover = self.focused = False
        self._photo = None
        super().__init__(parent, width=round(width * scale), height=round(height * scale),
                         bg=parent.cget('bg'), highlightthickness=0, bd=0, takefocus=state != 'disabled', cursor='hand2')
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda event: self._appearance(hover=True))
        self.bind('<Leave>', lambda event: self._appearance(hover=False))
        self.bind('<FocusIn>', lambda event: self._appearance(focused=True))
        self.bind('<FocusOut>', lambda event: self._appearance(focused=False))
        self.bind('<ButtonRelease-1>', self._click)
        self.bind('<Return>', self._click)
        self.bind('<space>', self._click)

    def _appearance(self, **values):
        for name, value in values.items():
            setattr(self, name, value)
        self._draw()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        for key in ('text', 'command', 'swatch', 'target'):
            if key in kwargs:
                setattr(self, key, kwargs.pop(key))
        if 'state' in kwargs:
            self._state = kwargs.pop('state')
            kwargs['takefocus'] = self._state != 'disabled'
            kwargs['cursor'] = 'arrow' if self._state == 'disabled' else 'hand2'
        if kwargs:
            super().configure(**kwargs)
        self._draw()

    config = configure

    def instate(self, states):
        return all((self._state == 'disabled') if state == 'disabled' else
                   (self._state != 'disabled') if state == '!disabled' else False for state in states)

    def _click(self, event=None):
        if self._state != 'disabled' and self.command:
            if event is None or event.type != tk.EventType.ButtonRelease or (
                    0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()):
                self.focus_set()
                self.command()
        return 'break'

    def _draw(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 2 or height < 2:
            return
        disabled = self._state == 'disabled'
        fill = '#EDEDF3' if disabled else ('#5544B6' if self.hover else ACCENT) if self.primary else (TINT if self.hover else WHITE)
        foreground = '#9998AA' if disabled else WHITE if self.primary else INK
        border = ACCENT if self.focused and not disabled else fill if self.primary else LINE
        image = Image.new('RGB', (width * 2, height * 2), self.cget('bg'))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, width * 2 - 2, height * 2 - 2), radius=round(20 * self.scale),
                               fill=color_hex(self.swatch) if self.swatch else fill, outline=border,
                               width=4 if self.focused and not disabled else 2)
        if self.target and self.target != self.swatch:
            size = round(14 * self.scale)
            draw.ellipse((width * 2 - size * 2 - 4, height * 2 - size * 2 - 4,
                          width * 2 - 4, height * 2 - 4), fill=color_hex(self.target), outline=WHITE, width=3)
        self._photo = ImageTk.PhotoImage(image.resize((width, height), Image.Resampling.LANCZOS), master=self)
        self.delete('all')
        self.create_image(0, 0, anchor='nw', image=self._photo)
        if self.number:
            x, radius = round(23 * self.scale), round(12 * self.scale)
            self.create_oval(x - radius, height / 2 - radius, x + radius, height / 2 + radius,
                             fill='#8373DB' if self.primary and not disabled else TINT, outline='')
            self.create_text(x, height / 2, text=self.number, fill=WHITE if self.primary and not disabled else ACCENT,
                             font=('Segoe UI', 10, 'bold'))
            self.create_text(round(47 * self.scale), height / 2, anchor='w', text=self.text,
                             fill=foreground, font=('Segoe UI', 11, 'bold'))
        elif self.text:
            self.create_text(width / 2, height / 2, text=self.text, fill=foreground,
                             font=('Segoe UI', 10, 'bold'))


class EmbImageApp:
    def __init__(self, root, processor):
        self.root, self.p = root, processor
        self.scale = max(1., float(root.tk.call('tk', 'scaling')) / (96 / 72))
        root.title('EmbImage · Preparador de logos')
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f'{min(self.px(1180), sw - 60)}x{min(self.px(780), sh - 90)}')
        root.minsize(min(self.px(820), sw - 60), min(self.px(610), sh - 90))
        root.configure(bg=BG)
        self.original = self.output = self.path = None
        self.chosen_bg = None
        self.custom_bg = (255, 255, 255)
        self.palette, self.color_replacements = [], {}
        self._palette_key = None
        self._document = self.job = 0
        self._ready_job = self._scheduled = self._refresh_scheduled = None
        self._working = self._closed = self._picking = False
        self._results = Queue()
        self._preview_bounds = None
        self._render_keys = [None, None]
        self._compact = None
        self._short = None
        self._pick_text = 'Escolher na imagem'
        self._error = None
        self._background_popup = None
        self.undo_stack = []
        self.remove_bg = tk.BooleanVar(value=True)
        self.bg_mode = tk.StringVar(value=self.p.BACKGROUNDS[1])
        self.anywhere = tk.BooleanVar(value=False)
        self.export_bg = tk.StringVar(value=self.p.EXPORT_BACKGROUNDS[0])
        self.final_background = tk.StringVar(value='Branco')
        self.palette_size = tk.IntVar(value=self.p.PALETTE_SIZE)
        self.edge_smoothness = tk.IntVar(value=2)
        self.keep_thin_details = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='1 · Abra uma imagem.')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TCheckbutton', background=WHITE, font=('Segoe UI', 10), padding=7)
        style.configure('Vertical.TScrollbar', background=LINE, troughcolor=WHITE,
                        borderwidth=0, arrowsize=self.px(10))
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=TINT,
                        borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)
        self.build()
        self._last_state = self._snapshot()
        root.bind('<Control-o>', lambda event: self.open_file())
        root.bind('<Control-s>', lambda event: self.save_png())
        root.bind('<Control-z>', lambda event: self.undo())
        root.bind('<Escape>', lambda event: self.cancel_pick())
        root.bind('<MouseWheel>', self._sidebar_wheel, add='+')
        root.bind('<Configure>', self._window_resize, add='+')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self._poll_id = root.after(80, self._poll_results)

    def px(self, value):
        return round(value * self.scale)

    def _label(self, parent, text='', *, size=10, bold=False, muted=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=MUTED if muted else INK,
                        font=('Segoe UI', size, 'bold' if bold else 'normal'), **kwargs)

    def _button(self, parent, text, command, **kwargs):
        return Button(parent, self.scale, text, command, **kwargs)

    def _heading(self, parent, number, title):
        row = tk.Frame(parent, bg=WHITE)
        badge = tk.Canvas(row, width=self.px(28), height=self.px(28), bg=WHITE, highlightthickness=0)
        badge.pack(side='left', padx=(0, self.px(9)))
        badge.create_oval(1, 1, self.px(27), self.px(27), fill=TINT, outline='')
        badge.create_text(self.px(14), self.px(14), text=str(number), fill=ACCENT, font=('Segoe UI', 11, 'bold'))
        self._label(row, title, bold=True, size=11).pack(side='left')
        self.numbered_sections.append((number, row))
        return row

    def _section(self, number, title):
        section = tk.Frame(self.sidebar_inner, bg=WHITE)
        section.pack(fill='x', pady=(0, self.px(14)))
        heading = self._heading(section, number, title)
        heading.pack(fill='x', pady=(0, self.px(8)))
        self._section_rows.append((section, heading))
        return section, heading

    def _counter(self, parent, variable, minus, plus):
        row = tk.Frame(parent, bg=WHITE)
        left = self._button(row, '−', minus, width=30, height=30)
        left.pack(side='left')
        self._label(row, textvariable=variable, size=12, bold=True, width=3).pack(side='left')
        right = self._button(row, '+', plus, width=30, height=30)
        right.pack(side='left')
        return row, left, right

    def build(self):
        header = self.header = tk.Frame(self.root, bg=BG)
        header.pack(fill='x', padx=self.px(26), pady=(self.px(18), self.px(14)))
        self._label(header, 'EmbImage', size=20, bold=True).pack(side='left')
        self._label(header, 'Preparador de logos', size=10, muted=True).pack(side='left', padx=self.px(14))
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(side='bottom', fill='x', padx=self.px(26), pady=(0, self.px(12)))
        self._label(footer, textvariable=self.status, size=9, muted=True, anchor='w').pack(fill='x')
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill='both', expand=True, padx=self.px(22), pady=(0, self.px(12)))
        self.sidebar = tk.Frame(self.body, bg=BG, width=self.px(326))
        self.sidebar.pack(side='left', fill='y', padx=(0, self.px(18)))
        self.sidebar.pack_propagate(False)
        self.controls_surface = Surface(self.sidebar, self.scale, padding=18)
        self.controls_surface.pack(fill='both', expand=True)
        left = self.controls_surface.content
        self.save_button = self._button(left, 'Salvar PNG', self.save_png, primary=True,
                                        number='6', height=46, state='disabled')
        self.save_button.pack(side='bottom', fill='x', pady=(self.px(12), 0))
        scroll_area = tk.Frame(left, bg=WHITE)
        scroll_area.pack(fill='both', expand=True)
        self.sidebar_canvas = tk.Canvas(scroll_area, bg=WHITE, highlightthickness=0, width=1, height=1)
        self.sidebar_scroll = ttk.Scrollbar(scroll_area, orient='vertical', command=self.sidebar_canvas.yview)
        self.sidebar_canvas.pack(side='left', fill='both', expand=True)
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scroll.set)
        self.sidebar_inner = tk.Frame(self.sidebar_canvas, bg=WHITE)
        self._sidebar_window = self.sidebar_canvas.create_window(0, 0, window=self.sidebar_inner, anchor='nw')
        self.sidebar_inner.bind('<Configure>', self._sidebar_fit)
        self.sidebar_canvas.bind('<Configure>', self._sidebar_fit)
        self.numbered_sections = []
        self._section_rows = []
        self.open_button = self._button(self.sidebar_inner, 'Abrir imagem', self.open_file, number='1', height=44)
        self.open_button.pack(fill='x', pady=(0, self.px(20)))

        section, self._bg_heading = self._section(2, 'Cor do fundo')
        row = self.bg_row = tk.Frame(section, bg=WHITE)
        row.pack(fill='x')
        self.bg_swatch = self._button(row, '', lambda: self.enable_click_pick(), width=38, height=36,
                                      swatch=(255, 255, 255), state='disabled')
        self.bg_swatch.pack(side='left', padx=(0, self.px(8)))
        self.pick_button = self._button(row, 'Escolher na imagem', self.enable_click_pick, height=36, state='disabled')
        self.pick_button.pack(side='left', fill='x', expand=True)

        section, self._final_heading = self._section(3, 'Fundo final')
        self.background_button = self._button(section, 'Branco   ▾', self._background_menu, height=38, state='disabled')
        self.background_button.pack(fill='x')

        section, heading = self._section(4, 'Cores')
        counter, self.minus_button, self.plus_button = self._counter(heading, self.palette_size,
            lambda: self.change_palette_size(-1), lambda: self.change_palette_size(1))
        counter.pack(side='right')
        self.palette_rows = tk.Frame(section, bg=WHITE, height=self.px(72))
        self.palette_rows.pack(fill='x')
        self.color_note = self._label(section, 'Clique para unir cores.', size=9, muted=True)
        self.color_note.pack(anchor='w', pady=(self.px(4), 0))

        section, heading = self._section(5, 'Bordas')
        counter, self.edge_minus, self.edge_plus = self._counter(heading, self.edge_smoothness,
            lambda: self.change_edge_smoothness(-1), lambda: self.change_edge_smoothness(1))
        counter.pack(side='right')
        self.edge_note = self._label(section, '1 · mais detalhes    3 · mais suave', size=9, muted=True)
        self.edge_note.pack(anchor='w')
        self.advanced_button = self._button(self.sidebar_inner, 'Opções avançadas', self.toggle_advanced, height=32)
        self.advanced_button.pack(fill='x')
        self._sync_controls()

        self.preview = Surface(self.body, self.scale, padding=20)
        self.preview.pack(side='left', fill='both', expand=True)
        right = self.preview.content
        self.file_label = self._label(right, 'Prévia', size=12, bold=True, anchor='w')
        self.file_label.pack(fill='x', pady=(0, self.px(14)))
        self.progress = ttk.Progressbar(right, mode='indeterminate', maximum=100)
        self.columns = tk.Frame(right, bg=WHITE)
        self.columns.pack(fill='both', expand=True)
        self.preview_columns, self.canvases, self.photos = [], [], [None, None]
        for index, title in enumerate(('Original', 'Resultado')):
            column = tk.Frame(self.columns, bg=WHITE)
            self.preview_columns.append(column)
            self._label(column, title, size=10, muted=True).pack(anchor='w', pady=(0, self.px(8)))
            canvas = tk.Canvas(column, bg=STAGE, highlightthickness=1, highlightbackground=LINE, width=1, height=1)
            canvas.pack(fill='both', expand=True)
            canvas.bind('<Configure>', self.request_refresh)
            self.canvases.append(canvas)
        self.canvases[0].bind('<Button-1>', self.pick_background)
        right.bind('<Configure>', self._preview_resize)

    def _window_resize(self, event):
        if event.widget is not self.root:
            return
        short = event.height < self.px(700)
        if short == self._short:
            return
        self._short = short
        self._pick_text = 'Escolher' if short else 'Escolher na imagem'
        self.header.pack_configure(pady=(self.px(12 if short else 18), self.px(10 if short else 14)))
        self.open_button.configure(height=self.px(38 if short else 44))
        self.open_button.pack_configure(pady=(0, self.px(10 if short else 20)))
        self.save_button.configure(height=self.px(42 if short else 46))
        self.bg_swatch.configure(width=self.px(28 if short else 38), height=self.px(30 if short else 36))
        self.pick_button.configure(text='Cancelar' if self._picking else self._pick_text,
                                   width=self.px(80 if short else 160), height=self.px(30 if short else 36))
        self.background_button.configure(width=self.px(115), height=self.px(30 if short else 38))
        self.advanced_button.configure(height=self.px(26 if short else 32))
        for section, heading in self._section_rows:
            section.pack_configure(pady=(0, self.px(10 if short else 14)))
            heading.pack_configure(pady=(0, self.px(4 if short else 8)))
        self.bg_row.pack_forget()
        self.background_button.pack_forget()
        if short:
            self.bg_row.pack(in_=self._bg_heading, side='right')
            self.background_button.pack(in_=self._final_heading, side='right')
            self.color_note.pack_forget()
            self.edge_note.pack_forget()
        else:
            self.bg_row.pack(in_=self._bg_heading.master, fill='x')
            self.background_button.pack(in_=self._final_heading.master, fill='x')
            self.color_note.pack(anchor='w', pady=(self.px(4), 0))
            self.edge_note.pack(anchor='w')

    def _sidebar_fit(self, event=None):
        width = self.sidebar_canvas.winfo_width()
        self.sidebar_canvas.itemconfigure(self._sidebar_window, width=max(1, width))
        self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox('all'))
        needed = self.sidebar_inner.winfo_reqheight() > self.sidebar_canvas.winfo_height() + 2
        if needed and not self.sidebar_scroll.winfo_manager():
            self.sidebar_scroll.pack(side='right', fill='y')
        elif not needed and self.sidebar_scroll.winfo_manager():
            self.sidebar_scroll.pack_forget()

    def _sidebar_wheel(self, event):
        widget = event.widget
        while widget is not None:
            if widget is self.sidebar:
                if self.sidebar_inner.winfo_height() > self.sidebar_canvas.winfo_height():
                    self.sidebar_canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
            widget = getattr(widget, 'master', None)

    def _sync_controls(self):
        loaded = self.original is not None
        for button in (self.pick_button, self.bg_swatch, self.background_button, self.advanced_button):
            button.configure(state='normal' if loaded else 'disabled')
        self.minus_button.configure(state='normal' if loaded and self.palette_size.get() > 2 else 'disabled')
        self.plus_button.configure(state='normal' if loaded and self.palette_size.get() < 12 else 'disabled')
        self.edge_minus.configure(state='normal' if loaded and self.edge_smoothness.get() > 1 else 'disabled')
        self.edge_plus.configure(state='normal' if loaded and self.edge_smoothness.get() < 3 else 'disabled')
        self.bg_swatch.configure(swatch=self.chosen_bg or (255, 255, 255))
        value = 'Manter original' if not self.remove_bg.get() else (
            ('Branco', 'Transparente', 'Preto', 'Outra cor…')[self.p.EXPORT_BACKGROUNDS.index(self.export_bg.get())])
        self.final_background.set(value)
        self.background_button.configure(text=value + '   ▾')

    def _background_menu(self):
        # tk_popup pode retornar antes da escolha; o menu vive até fechar a janela.
        if self._background_popup is None:
            self._background_popup = tk.Menu(self.root, tearoff=False, bg=WHITE, fg=INK, activebackground=TINT,
                                            activeforeground=ACCENT, font=('Segoe UI', 11), relief='flat', bd=1)
            for text in ('Manter original', 'Branco', 'Transparente', 'Preto', 'Outra cor…'):
                self._background_popup.add_radiobutton(
                    label=text, variable=self.final_background, value=text,
                    command=lambda label=text: self._choose_final_background(label))
        menu = self._background_popup
        try:
            menu.tk_popup(self.background_button.winfo_rootx(),
                          self.background_button.winfo_rooty() + self.background_button.winfo_height())
        finally:
            menu.grab_release()

    def _choose_final_background(self, label):
        if label == 'Manter original':
            self.remove_bg.set(False)
            self._commit(reset_palette=True)
        else:
            index = ('Branco', 'Transparente', 'Preto', 'Outra cor…').index(label)
            self.choose_export_option(index)

    def choose_export_option(self, index):
        if index == 3:
            rgb, _ = colorchooser.askcolor(color=color_hex(self.custom_bg), title='Cor do fundo', parent=self.root)
            if rgb is None:
                self.export_bg.set(self._last_state['export'])
                self._sync_controls()
                return
            self.custom_bg = tuple(round(value) for value in rgb)
        changed_removal = not self.remove_bg.get()
        self.remove_bg.set(True)
        self.export_bg.set(self.p.EXPORT_BACKGROUNDS[index])
        self._commit(reset_palette=changed_removal, reprocess=changed_removal)

    def _snapshot(self):
        return dict(remove=self.remove_bg.get(), mode=self.bg_mode.get(), chosen=self.chosen_bg,
                    anywhere=self.anywhere.get(), export=self.export_bg.get(), custom=self.custom_bg,
                    count=self.palette_size.get(), smooth=self.edge_smoothness.get(),
                    thin=self.keep_thin_details.get(), replacements=self.color_replacements.copy())

    def _restore(self, state):
        for variable, key in ((self.remove_bg, 'remove'), (self.bg_mode, 'mode'), (self.anywhere, 'anywhere'),
                              (self.export_bg, 'export'), (self.palette_size, 'count'),
                              (self.edge_smoothness, 'smooth'), (self.keep_thin_details, 'thin')):
            variable.set(state[key])
        self.chosen_bg, self.custom_bg = state['chosen'], state['custom']
        self.color_replacements = state['replacements'].copy()

    def _commit(self, *, reset_palette=False, reprocess=True):
        if self.original is None:
            return
        if reset_palette:
            self.color_replacements = {}
        state = self._snapshot()
        if state == self._last_state:
            return
        self.undo_stack.append(self._last_state)
        self.undo_stack = self.undo_stack[-30:]
        self._last_state = state
        self._sync_controls()
        if reprocess:
            self.queue()
        else:
            self.status.set('Pronto para salvar.')
            self.request_refresh()

    def undo(self):
        if self.undo_stack:
            self.cancel_pick()
            self._restore(self.undo_stack.pop())
            self._last_state = self._snapshot()
            self._sync_controls()
            self.queue()

    def _defaults(self):
        self.remove_bg.set(True)
        self.bg_mode.set(self.p.BACKGROUNDS[1])
        self.chosen_bg = self.p.color_at_corner(self.original)
        self.anywhere.set(False)
        self.export_bg.set(self.p.EXPORT_BACKGROUNDS[0])
        self.custom_bg = (255, 255, 255)
        self.palette_size.set(self.p.PALETTE_SIZE)
        self.edge_smoothness.set(2)
        self.keep_thin_details.set(False)
        self.color_replacements = {}

    def change_palette_size(self, amount):
        self.palette_size.set(max(2, min(12, self.palette_size.get() + amount)))
        self._commit(reset_palette=True)

    def change_edge_smoothness(self, amount):
        self.edge_smoothness.set(max(1, min(3, self.edge_smoothness.get() + amount)))
        self._commit()

    def _change_background(self):
        self.cancel_pick()
        self._commit(reset_palette=True)

    def toggle_advanced(self):
        if self.original is None:
            return
        dialog = self._dialog('Opções avançadas')
        frame = dialog.content
        ttk.Checkbutton(frame, text='Preservar detalhes finos', variable=self.keep_thin_details,
                        command=self._commit).pack(anchor='w')
        ttk.Checkbutton(frame, text='Remover fundo em áreas internas', variable=self.anywhere,
                        command=self._change_background).pack(anchor='w')
        self._button(frame, 'Fechar', dialog.destroy, width=240).pack(fill='x', pady=(self.px(12), 0))
        self._center_dialog(dialog)

    def _dialog(self, title):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=WHITE)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.content = tk.Frame(dialog, bg=WHITE, padx=self.px(20), pady=self.px(20))
        dialog.content.pack(fill='both', expand=True)
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        return dialog

    def _center_dialog(self, dialog):
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f'+{max(0, x)}+{max(0, y)}')
        dialog.grab_set()
        dialog.focus_set()

    def _current_palette_key(self):
        return (self._document, self.remove_bg.get(), self.bg_mode.get(), self.chosen_bg,
                self.anywhere.get(), self.palette_size.get())

    def render_palette(self):
        for child in self.palette_rows.winfo_children():
            child.destroy()
        if self._palette_key != self._current_palette_key() or not self.palette:
            self._label(self.palette_rows, '…' if not self._error else '—', muted=True).pack(anchor='w')
            return
        for index, source in enumerate(self.palette):
            target = self.color_replacements.get(source, source)
            button = self._button(self.palette_rows, '', lambda color=source: self.choose_palette_color(color),
                                  width=34, height=32, swatch=source, target=target)
            button.grid(row=index // 6, column=index % 6, padx=(0, self.px(8)), pady=(0, self.px(7)))

    def choose_palette_color(self, source):
        if self._palette_key != self._current_palette_key() or source not in self.palette:
            return
        dialog = self._dialog('Unir cores')
        frame = dialog.content
        self._label(frame, 'Escolha a outra cor', size=12, bold=True).pack(anchor='w', pady=(0, self.px(15)))
        options = tk.Frame(frame, bg=WHITE)
        options.pack(fill='x')

        def apply(target):
            if target == source:
                self.color_replacements.pop(source, None)
            else:
                self.color_replacements[source] = target
            self._commit()
            self.render_palette()
            dialog.destroy()

        for index, target in enumerate(color for color in self.palette if color != source):
            self._button(options, '', lambda color=target: apply(color), width=42, height=42, swatch=target).grid(
                row=index // 5, column=index % 5, padx=self.px(4), pady=self.px(4))
        if source in self.color_replacements:
            self._button(frame, 'Desfazer união', lambda: apply(source)).pack(fill='x', pady=(self.px(12), 0))
        self._button(frame, 'Cancelar', dialog.destroy).pack(fill='x', pady=(self.px(10), 0))
        self._center_dialog(dialog)

    def enable_click_pick(self):
        if self.original is None:
            return
        if self._picking:
            self.cancel_pick()
            return
        self._picking = True
        self.pick_button.configure(text='Cancelar')
        self.save_button.configure(state='disabled')
        self.canvases[0].configure(cursor='crosshair', highlightbackground=ACCENT, highlightthickness=2)
        self.status.set('2 · Clique no fundo da imagem original.')

    def cancel_pick(self):
        if self._picking:
            self._picking = False
            self.pick_button.configure(text=self._pick_text)
            self.canvases[0].configure(cursor='arrow', highlightbackground=LINE, highlightthickness=1)
            ready = self.output is not None and self._ready_job == self.job
            self.save_button.configure(state='normal' if ready else 'disabled')
            self.status.set('Pronto para salvar.' if ready else 'Preparando…')

    def pick_background(self, event):
        if not self._picking or self.original is None or not self._preview_bounds:
            return
        px, py, width, height = self._preview_bounds
        canvas = self.canvases[0]
        cx, cy = canvas.canvasx(event.x), canvas.canvasy(event.y)
        if not (px <= cx < px + width and py <= cy < py + height):
            return
        x = min(self.original.width - 1, int((cx - px) * self.original.width / width))
        y = min(self.original.height - 1, int((cy - py) * self.original.height / height))
        if self.original.getpixel((x, y))[3] == 0:
            self.status.set('Esta área já está sem fundo. Escolha uma área com cor.')
            return
        sample = np.asarray(self.original)[max(0, y - 2):y + 3, max(0, x - 2):x + 3, :3]
        self.chosen_bg = tuple(int(value) for value in np.median(sample.reshape(-1, 3), axis=0))
        self.bg_mode.set(self.p.BACKGROUNDS[2])
        self.remove_bg.set(True)
        self.cancel_pick()
        self._commit(reset_palette=True)

    def _preview_resize(self, event):
        compact = event.width < self.px(540)
        if compact != self._compact:
            self._compact = compact
            self._layout_previews()
        self.file_label.configure(wraplength=max(self.px(180), event.width - self.px(8)))

    def _layout_previews(self):
        self._preview_bounds = None
        self._render_keys = [None, None]
        for index in range(2):
            self.columns.rowconfigure(index, weight=0, uniform='')
            self.columns.columnconfigure(index, weight=0, uniform='')
            self.preview_columns[index].grid_forget()
        for index, column in enumerate(self.preview_columns):
            row, col = (index, 0) if self._compact else (0, index)
            column.grid(row=row, column=col, sticky='nsew',
                        padx=((0, self.px(8)) if index == 0 else (self.px(8), 0)) if not self._compact else 0,
                        pady=(0, self.px(14)) if self._compact and index == 0 else 0)
            self.columns.rowconfigure(row, weight=1, uniform='previews')
            self.columns.columnconfigure(col, weight=1, uniform='previews')
        self.request_refresh()

    def request_refresh(self, event=None):
        if not self._closed:
            if self._refresh_scheduled is not None:
                self.root.after_cancel(self._refresh_scheduled)
            self._refresh_scheduled = self.root.after(50, self.refresh)

    def refresh(self):
        self._refresh_scheduled = None
        for index, source in enumerate((self.original, self.output)):
            canvas = self.canvases[index]
            if not canvas.winfo_ismapped():
                continue
            width, height = canvas.winfo_width(), canvas.winfo_height()
            key = (id(source), width, height, self.export_bg.get(), self.custom_bg)
            if key == self._render_keys[index]:
                continue
            self._render_keys[index] = key
            canvas.delete('all')
            if source is None:
                if index == 0:
                    x, y, size = width // 2, height // 2 - self.px(14), self.px(23)
                    canvas.create_rectangle(x - size, y - size, x + size, y + size, outline='#C8C5D9', width=2)
                    canvas.create_line(x - size + 5, y + size - 5, x - 3, y - 4, x + 6, y + 5,
                                       x + 12, y - 1, x + size - 4, y + size - 5, fill='#C8C5D9', width=2)
                    canvas.create_text(x, y + self.px(48), text='Abra uma imagem', fill=MUTED, font=('Segoe UI', 10))
                continue
            factor = min(max(1, width - self.px(26)) / source.width, max(1, height - self.px(26)) / source.height)
            image = source.resize((max(1, round(source.width * factor)), max(1, round(source.height * factor))),
                                  Image.Resampling.LANCZOS)
            if index == 1 and self.export_bg.get() != self.p.EXPORT_BACKGROUNDS[1]:
                image = self.p.apply_export_background(image, self.export_bg.get(), self.custom_bg)
            else:
                backdrop = Image.new('RGBA', image.size, WHITE)
                draw = ImageDraw.Draw(backdrop)
                step = self.px(12)
                for y in range(0, image.height, step):
                    for x in range(0, image.width, step):
                        if (x // step + y // step) % 2:
                            draw.rectangle((x, y, x + step - 1, y + step - 1), fill='#EBEAF1')
                backdrop.alpha_composite(image.convert('RGBA'))
                image = backdrop.convert('RGB')
            px, py = (width - image.width) // 2, (height - image.height) // 2
            self.photos[index] = ImageTk.PhotoImage(image, master=self.root)
            canvas.create_image(px, py, anchor='nw', image=self.photos[index])
            if index == 0:
                self._preview_bounds = (px, py, image.width, image.height)

    def open_file(self):
        filename = filedialog.askopenfilename(parent=self.root, title='Abrir imagem',
            filetypes=[('Imagens', '*.png *.jpg *.jpeg *.webp *.bmp'), ('Todos os arquivos', '*.*')])
        if filename:
            self.open_path(filename)

    def open_path(self, filename):
        try:
            original = self.p.load_image(filename)
        except Exception:
            messagebox.showerror('Não foi possível abrir', 'Escolha uma imagem PNG, JPG, WEBP ou BMP válida.', parent=self.root)
            return
        self.cancel_pick()
        self.original, self.path, self.output = original, str(filename), None
        self._document += 1
        self.palette, self.undo_stack = [], []
        self._palette_key = None
        self._defaults()
        self._last_state = self._snapshot()
        self._sync_controls()
        self.file_label.configure(text=Path(filename).name)
        self._render_keys = [None, None]
        self.sidebar_canvas.yview_moveto(0)
        self.queue()

    def queue(self):
        if self.original is None or self._closed:
            return
        self.job += 1
        self._ready_job, self._error = None, None
        self.save_button.configure(state='disabled')
        if not self._picking:
            self.status.set('Preparando…')
        self.progress.pack(fill='x', pady=(self.px(10), 0), side='bottom')
        self.progress.start(12)
        self.render_palette()
        if self._scheduled is not None:
            self.root.after_cancel(self._scheduled)
        self._scheduled = self.root.after(250, self.start)
        self.request_refresh()

    def start(self):
        self._scheduled = None
        if self._working or self._closed:
            return
        self._working = True
        job, image, key = self.job, self.original, self._current_palette_key()
        palette = self.palette.copy() if self._palette_key == key else None
        replacements = self.color_replacements.copy()
        bg_mode = self.bg_mode.get() if self.remove_bg.get() else self.p.BACKGROUNDS[0]
        bg_color, anywhere = self.chosen_bg, self.anywhere.get()
        count, smooth, thin = self.palette_size.get(), self.edge_smoothness.get(), self.keep_thin_details.get()

        def worker():
            try:
                detected = palette
                if detected is None:
                    rgba = np.asarray(image.convert('RGBA')).copy()
                    if bg_mode != self.p.BACKGROUNDS[0]:
                        rgba = self.p.remove_background(rgba, bg_color, self.p.BACKGROUND_TOLERANCE, anywhere)
                    detected = list(dict.fromkeys(self.p.detect_palette(rgba, count)))
                result = self.p.process(image, detected, replacements, bg_mode, bg_color, anywhere, smooth, thin)
                self._results.put((job, key, detected, result, None))
            except Exception as exc:
                self._results.put((job, key, [], None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_results(self):
        if self._closed:
            return
        try:
            while True:
                job, key, palette, result, error = self._results.get_nowait()
                self._working = False
                if job == self.job:
                    self.finish(job, key, palette, result, error)
                elif self._scheduled is None:
                    self.start()
        except Empty:
            pass
        self._poll_id = self.root.after(80, self._poll_results)

    def finish(self, job, key, palette, result, error):
        if job != self.job:
            return
        self.progress.stop()
        self.progress.pack_forget()
        self._error = error
        if error:
            self.status.set('Não foi possível preparar. Abra a imagem novamente.')
        else:
            self.palette, self._palette_key, self.output = palette, key, result
            self._ready_job = job
            self.save_button.configure(state='disabled' if self._picking else 'normal')
            if not self._picking:
                self.status.set('6 · Pronto para salvar.')
        self._render_keys[1] = None
        self.render_palette()
        self.request_refresh()

    def save_png(self):
        if self.output is None or self._ready_job != self.job or self._picking:
            return
        job = self.job
        filename = filedialog.asksaveasfilename(parent=self.root, title='Salvar PNG', defaultextension='.png',
            initialfile=Path(self.path).stem + '_para_bordado.png', filetypes=[('Imagem PNG', '*.png')])
        if not filename or self._ready_job != job or self.job != job:
            return
        try:
            self.p.apply_export_background(self.output, self.export_bg.get(), self.custom_bg).save(filename, 'PNG')
            self.status.set('Imagem salva.')
        except Exception:
            messagebox.showerror('Não foi possível salvar', 'Tente salvar em outra pasta.', parent=self.root)

    def close(self):
        self._closed = True
        for callback in (self._scheduled, self._refresh_scheduled, self._poll_id):
            if callback is not None:
                self.root.after_cancel(callback)
        self.progress.stop()
        self.root.destroy()
