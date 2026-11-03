"""Tk root ownership for fallback overlays."""


class TkRootProvider:
    def __init__(self):
        self.root = None

    def get(self, *, tkinter_available, tk_module):
        if not tkinter_available:
            return None

        if self.root is None:
            self.root = tk_module.Tk()
            self.root.withdraw()
        return self.root


__all__ = ['TkRootProvider']
