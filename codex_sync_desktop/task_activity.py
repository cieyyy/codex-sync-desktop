"""A shared, visible task status for the workspace and setup wizard."""
from time import monotonic
from tkinter import ttk


class TaskActivity(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style='Panel.TFrame', padding=(16, 8))
        self.active = False
        self.started = None
        self.timer = None
        self.columnconfigure(0, weight=1)
        self.label = ttk.Label(self, text='就绪', style='Task.TLabel', anchor='w', wraplength=440)
        self.label.grid(row=0, column=0, sticky='ew', padx=(0, 16))
        self.elapsed = ttk.Label(self, text='', style='PanelMuted.TLabel')
        self.elapsed.grid(row=0, column=1, sticky='e')
        self.bar = ttk.Progressbar(self, mode='indeterminate', style='Task.Horizontal.TProgressbar')
        self.bind('<Destroy>', self._destroy_timer, add='+')

    def set_state(self, text, *, active, failed=False):
        if active and not self.active:
            self.started = monotonic()
            self.bar.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 0))
            self.bar.start(80)
        self.active = active
        self.label.configure(text=text, style='TaskError.TLabel' if failed else 'Task.TLabel')
        if not active:
            self.bar.stop()
            self.bar.grid_remove()
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self._tick()

    def _tick(self):
        self.timer = None
        if self.started is not None:
            seconds = int(monotonic() - self.started)
            self.elapsed.configure(text=f'已用 {seconds // 60:02d}:{seconds % 60:02d}')
        if self.active:
            self.timer = self.after(1000, self._tick)

    def _destroy_timer(self, event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
