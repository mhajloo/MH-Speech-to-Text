"""Global hold-to-talk hotkey via a low-level keyboard hook (WH_KEYBOARD_LL).

The hook only records key state and queues events; callbacks run on a separate
dispatcher thread, because Windows silently removes a hook that responds slowly.
While the hotkey's modifiers are held, its trigger key (e.g. Q in ctrl+q) is
swallowed so the focused app never sees the shortcut.
"""
import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_QUIT = 0x12
LLKHF_INJECTED = 0x10

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

MODIFIERS = {
    "ctrl": {0xA2, 0xA3, 0x11}, "lctrl": {0xA2}, "rctrl": {0xA3},
    "shift": {0xA0, 0xA1, 0x10}, "lshift": {0xA0}, "rshift": {0xA1},
    "alt": {0xA4, 0xA5, 0x12}, "lalt": {0xA4}, "ralt": {0xA5},
    "win": {0x5B, 0x5C}, "lwin": {0x5B}, "rwin": {0x5C},
}
NAMED = {
    "space": 0x20, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "enter": 0x0D,
    "capslock": 0x14, "insert": 0x2D, "pause": 0x13, "scrolllock": 0x91,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}


def key_to_vks(name: str) -> set:
    name = name.strip().lower()
    if name in MODIFIERS:
        return MODIFIERS[name]
    if name in NAMED:
        return {NAMED[name]}
    if len(name) == 1 and name.isalnum():
        return {ord(name.upper())}
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return {0x70 + int(name[1:]) - 1}
    raise ValueError(f"unknown key: {name!r}")


# virtual-key → name, for recording a new hotkey (side-specific modifiers)
VK_NAMES = {0xA2: "lctrl", 0xA3: "rctrl", 0xA0: "lshift", 0xA1: "rshift", 0xA4: "lalt",
            0xA5: "ralt", 0x5B: "lwin", 0x5C: "rwin", 0x11: "ctrl", 0x10: "shift", 0x12: "alt",
            **{v: k for k, v in NAMED.items() if k != "escape"},
            **{0x70 + i: f"f{i + 1}" for i in range(24)},
            **{ord(ch): ch.lower() for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}}
GENERIC = {"lctrl": "ctrl", "rctrl": "ctrl", "lshift": "shift", "rshift": "shift",
           "lalt": "alt", "ralt": "alt", "lwin": "win", "rwin": "win"}
MOD_ORDER = ["ctrl", "lctrl", "rctrl", "alt", "lalt", "ralt", "shift", "lshift", "rshift",
             "win", "lwin", "rwin"]
# shortcuts every app relies on: never take them over
RESERVED = {"ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "ctrl+f",
            "ctrl+p", "ctrl+n", "ctrl+o", "ctrl+w", "ctrl+t", "alt+tab", "alt+f4"}


def combo_from_keys(names) -> str:
    """Normalise recorded keys into a combo string: with an ordinary key the
    modifiers are generic (ctrl+q); a lone modifier keeps its side (rctrl)."""
    mods = [n for n in names if n in MOD_ORDER]
    keys = [n for n in names if n not in MOD_ORDER]
    if keys or len(mods) > 1:
        mods = sorted({GENERIC.get(m, m) for m in mods}, key=MOD_ORDER.index)
    return "+".join(mods + keys)


def check_combo(combo: str):
    """Returns None if usable, else a Persian reason why not."""
    parts = combo.split("+")
    mods = [p for p in parts if p in MOD_ORDER]
    keys = [p for p in parts if p not in MOD_ORDER]
    if not parts or parts == [""]:
        return "کلیدی ثبت نشد."
    if combo in RESERVED:
        return "این ترکیب میان‌بر رایج ویندوز و برنامه‌هاست."
    if keys and not mods and not any(k.startswith("f") and k[1:].isdigit() or k in (
            "pause", "scrolllock", "insert", "capslock") for k in keys):
        return "یک حرف یا عدد تنها، تایپ کردن را مختل می‌کند؛ با Ctrl یا Alt ترکیبش کنید."
    if combo in ("ctrl", "shift", "alt", "win", "lctrl", "lshift", "lalt", "lwin"):
        return "این کلید در میان‌برهای زیادی استفاده می‌شود؛ ترکیب دیگری انتخاب کنید."
    return None


class HoldHotkey:
    def __init__(self, combo: str, on_press, on_release, on_cancel=None, cancel_key="esc"):
        self.set_combo(combo)
        self.cancel_vks = key_to_vks(cancel_key) if cancel_key else set()
        self.callbacks = {"press": on_press, "release": on_release, "cancel": on_cancel}

        self.down = set()
        self.swallowed = set()
        self.active = False
        self.suspended = False      # while settings records a new hotkey, etc.
        self.cancel_armed = False   # toggle mode: Esc cancels even though no key is held
        self._capture = None        # (callback, keys seen) while recording a new hotkey
        self.events = queue.Queue()
        self._proc_ref = HOOKPROC(self._proc)  # keep a reference or ctypes frees it
        self._thread_id = None

    def set_combo(self, combo: str):
        parts = [p.strip() for p in combo.lower().split("+") if p.strip()]
        groups = [key_to_vks(p) for p in parts]
        triggers = [g for p, g in zip(parts, groups) if p not in MODIFIERS]
        # assign the finished values last: the hook thread may read them any time
        self.mod_groups = [g for p, g in zip(parts, groups) if p in MODIFIERS]
        self.trigger_vks = set().union(*triggers) if triggers else set()
        self.groups = groups
        self.combo = combo

    def begin_capture(self, callback):
        """Record the next key combination instead of acting on keys; calls
        callback(combo) once every key is released (combo None if Esc alone)."""
        self._capture = (callback, [])

    def end_capture(self):
        self._capture = None

    # -- hook side (must return fast) --
    def _group_down(self, group):
        return any(vk in self.down for vk in group)

    def _proc(self, n_code, w_param, l_param):
        if n_code == 0:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not kb.flags & LLKHF_INJECTED:
                is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if self._handle(kb.vkCode, is_down):
                    return 1
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle(self, vk, is_down) -> bool:
        if is_down:
            self.down.add(vk)
        else:
            self.down.discard(vk)

        if self._capture is not None:
            return self._handle_capture(vk, is_down)
        if self.suspended:
            return False
        suppress = False

        if vk in self.cancel_vks and is_down and (self.active or self.cancel_armed):
            self.events.put("cancel")
            self.swallowed.add(vk)
            return True
        # swallow the trigger while its modifiers are held, and keep swallowing its
        # auto-repeat until it is released (even if the modifiers go up first)
        if vk in self.trigger_vks and is_down:
            if vk in self.swallowed or all(self._group_down(g) for g in self.mod_groups):
                self.swallowed.add(vk)
                suppress = True
        if not is_down and vk in self.swallowed:
            self.swallowed.discard(vk)
            suppress = True

        now = all(self._group_down(g) for g in self.groups)
        if now and not self.active:
            self.active = True
            self.events.put("press")
        elif not now and self.active:
            self.active = False
            self.events.put("release")
        return suppress

    def _handle_capture(self, vk, is_down) -> bool:
        callback, seen = self._capture
        name = VK_NAMES.get(vk)
        if is_down and name and name not in seen:
            seen.append(name)
        if not is_down and not self.down:  # everything released: done
            self._capture = None
            keys = [n for n in seen if n != "esc"]
            combo = combo_from_keys(keys) if keys else None
            self.events.put(lambda: callback(combo))
        return True  # keys pressed while recording must not type anywhere

    # -- threads --
    def _hook_loop(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc_ref,
                                        kernel32.GetModuleHandleW(None), 0)
        if not hook:
            raise ctypes.WinError(ctypes.get_last_error())
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(hook)

    def _dispatch_loop(self):
        while True:
            ev = self.events.get()
            if ev is None:
                return
            cb = ev if callable(ev) else self.callbacks.get(ev)
            if cb:
                try:
                    cb()
                except Exception:  # a failing callback must not kill the hotkey
                    import traceback
                    traceback.print_exc()

    def start(self):
        threading.Thread(target=self._hook_loop, name="kbd-hook", daemon=True).start()
        threading.Thread(target=self._dispatch_loop, name="kbd-dispatch", daemon=True).start()

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self.events.put(None)
