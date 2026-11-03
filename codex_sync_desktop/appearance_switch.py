"""Sun and moon controls with native radio-button semantics and crisp icons."""
import math
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from .ui_theme import COLORS


class AppearanceSwitch(ttk.Frame):
    def __init__(self, parent, variable, command):
        super().__init__(parent)
        self.variable = variable
        self.command = command
        self.images = []
        self.tooltip = None
        self.tooltip_timer = None
        self.buttons = {}
        style = ttk.Style(self)
        style.layout('Appearance.TRadiobutton', [('Radiobutton.padding', {
            'sticky': 'nswe', 'children': [('Radiobutton.focus', {
                'sticky': 'nswe', 'children': [('Radiobutton.label', {'sticky': 'nswe'})]})]})])
        for value, name in (('浅色', 'sun'), ('深色', 'moon')):
            button = ttk.Radiobutton(self, text=value+'模式', value=value, variable=variable,
                                     command=self._choose, style='Appearance.TRadiobutton', takefocus=True)
            button.pack(side='left', padx=(0, 4) if name == 'sun' else 0)
            button.bind('<Enter>', lambda _event, b=button, v=value: self._schedule_tooltip(b, v+'模式'))
            button.bind('<Leave>', self._hide_tooltip)
            button.bind('<ButtonPress-1>', self._hide_tooltip, add='+')
            button.bind('<Left>', lambda _event: self._select('浅色'))
            button.bind('<Right>', lambda _event: self._select('深色'))
            self.buttons[name] = button
        self.bind('<Destroy>', self._hide_tooltip, add='+')
        self.refresh()

    def _choose(self):
        self._hide_tooltip()
        self.command()

    def _select(self, value):
        self.variable.set(value)
        self.buttons['sun' if value == '浅色' else 'moon'].focus_set()
        self._choose()
        return 'break'

    def refresh(self):
        style = ttk.Style(self)
        style.configure('Appearance.TRadiobutton', background=COLORS['background'],
                        padding=0, borderwidth=0, focuscolor=COLORS['primary'])
        style.map('Appearance.TRadiobutton', background=[('active', COLORS['background'])])
        # Keep old references alive until all native buttons use the new images.
        images = []
        for name, button in self.buttons.items():
            variants = [self._icon(name, state) for state in ('normal', 'selected', 'hover')]
            images.extend(variants)
            button.configure(image=(variants[0], 'selected', variants[1], 'active', variants[2]))
        self.images = images

    def _icon(self, name, state):
        scale = 3
        image = Image.new('RGBA', (40*scale, 36*scale))
        draw = ImageDraw.Draw(image)
        fill = COLORS['selection'] if state == 'selected' else COLORS['surface_alt']
        ink = COLORS['primary'] if state == 'selected' else COLORS['text'] if state == 'hover' else COLORS['text_muted']
        draw.rounded_rectangle((1*scale, 1*scale, 39*scale, 35*scale), radius=10*scale,
                               fill=fill, outline=COLORS['border'] if state == 'hover' else fill, width=scale)
        def line(points):
            draw.line([(x*scale, y*scale) for x,y in points], fill=ink, width=2*scale, joint='curve')
        if name == 'sun':
            draw.ellipse((16*scale, 14*scale, 24*scale, 22*scale), outline=ink, width=2*scale)
            for index in range(8):
                angle = index*math.pi/4
                line([(20+7*math.cos(angle), 18+7*math.sin(angle)),
                      (20+10*math.cos(angle), 18+10*math.sin(angle))])
        else:
            outer = [(20+8*math.cos(math.radians(245.7-index*221.4/48)),
                      18+8*math.sin(math.radians(245.7-index*221.4/48))) for index in range(49)]
            inner = [(24+8*math.cos(math.radians(65.7+index*138.6/32)),
                      14+8*math.sin(math.radians(65.7+index*138.6/32))) for index in range(33)]
            line(outer+inner+[outer[0]])
        return ImageTk.PhotoImage(image.resize((40,36), Image.Resampling.LANCZOS), master=self)

    def _schedule_tooltip(self, button, text):
        self._hide_tooltip()
        def show():
            self.tooltip_timer = None
            self.tooltip = tk.Toplevel(self)
            self.tooltip.overrideredirect(True)
            self.tooltip.attributes('-topmost', True)
            ttk.Label(self.tooltip, text=text, style='Panel.TLabel', padding=(10,6)).pack()
            self.tooltip.geometry(f'+{button.winfo_rootx()-8}+{button.winfo_rooty()+button.winfo_height()+6}')
        self.tooltip_timer = self.after(500, show)

    def _hide_tooltip(self, _event=None):
        if self.tooltip_timer is not None:
            self.after_cancel(self.tooltip_timer)
            self.tooltip_timer = None
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None
