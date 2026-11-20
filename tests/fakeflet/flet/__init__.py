"""測試用的假 Flet：只記錄介面長什麼樣子，讓測試可以「按按鈕」。不是真的 Flet。"""
class _Any(str):
    def __call__(self, *a, **k): return _Any(self)
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return _Any(f"{self}.{n}")
class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"): raise AttributeError(name)
        return _Any(f"{cls.__name__}.{name}")
class Control(metaclass=_Meta):
    def __init__(self, *args, **kw):
        self.args = args
        self.__dict__.update(kw)
    def update(self): UPDATES.append(self)
UPDATES = []
_cache = {}
def __getattr__(name):
    if name.startswith("__"): raise AttributeError(name)
    if name not in _cache:
        _cache[name] = _Meta(name, (Control,), {})
    return _cache[name]
_PREFS = {}
class SharedPreferences(Control):
    async def get(self, k): return _PREFS.get(k)
    async def set(self, k, v): _PREFS[k] = v; return True
    async def remove(self, k): return _PREFS.pop(k, None) is not None
class _File:
    def __init__(self, b): self.bytes = b; self.path = None; self.name = "x.jpg"
NEXT_PICK = []
SAVED = []
class FilePicker(Control):
    async def pick_files(self, **kw): return [_File(NEXT_PICK.pop())] if NEXT_PICK else []
    async def save_file(self, **kw): SAVED.append(kw); return None
class _Platform:
    def is_mobile(self): return False
LAUNCHED = []
class Page(Control):
    def __init__(self):
        self.controls=[]; self.dialogs=[]; self.web=True; self.platform=_Platform(); self.width=390
    def add(self,*c): self.controls.extend(c)
    def update(self): pass
    def show_dialog(self,d): self.dialogs.append(d)
    def pop_dialog(self): self.dialogs.pop() if self.dialogs else None
    async def launch_url(self, u): LAUNCHED.append(u)
def run(*a, **k): pass
