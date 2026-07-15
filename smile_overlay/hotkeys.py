"""전역 단축키 관리 (Windows RegisterHotKey 기반).

오버레이가 클릭 통과(투명) 상태여도, 다른 프로그램(exocad)에 포커스가
있어도 전역 단축키가 동작한다. Windows가 아닌 환경에서는 자동으로
비활성화되며, 그 경우 컨트롤 패널에 포커스가 있을 때만 QShortcut
폴백으로 동작한다.
"""
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter

IS_WIN = sys.platform.startswith("win")
if IS_WIN:
    import ctypes
    import ctypes.wintypes as wintypes
    _user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_NAMES = {
    "CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
    "ALT": MOD_ALT,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN, "META": MOD_WIN,
}

_SPECIAL_VK = {
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D, "ENTER": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08,
    "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDOWN": 0x22,
    "INS": 0x2D, "INSERT": 0x2D, "DEL": 0x2E, "DELETE": 0x2E,
    "-": 0xBD, "=": 0xBB, "+": 0xBB,
    "`": 0xC0, "~": 0xC0, "[": 0xDB, "]": 0xDD,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}
# F1~F24
for _i in range(1, 25):
    _SPECIAL_VK[f"F{_i}"] = 0x70 + (_i - 1)


def parse_hotkey(text):
    """'Ctrl+Alt+1' 형식 문자열 → (win32 modifiers, virtual key). 실패 시 None"""
    if not text:
        return None
    text = text.strip()
    # 'Ctrl+Alt++' 처럼 '+' 키 자체인 경우 처리
    if text.endswith("++"):
        parts = [p for p in text[:-2].split("+") if p] + ["+"]
    else:
        parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return None

    mods = 0
    key = None
    for part in parts:
        upper = part.upper()
        if upper in _MODIFIER_NAMES:
            mods |= _MODIFIER_NAMES[upper]
        else:
            key = upper
    if key is None:
        return None

    if key in _SPECIAL_VK:
        return mods, _SPECIAL_VK[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return mods, ord(key)
    return None


class GlobalHotkeys(QAbstractNativeEventFilter):
    """RegisterHotKey 기반 전역 단축키. install() 후 register()로 등록."""

    def __init__(self):
        super().__init__()
        self.available = IS_WIN
        self._callbacks = {}   # hotkey id -> callable
        self._next_id = 0xA100

    def install(self, app):
        app.installNativeEventFilter(self)

    def clear(self):
        if IS_WIN:
            for hid in self._callbacks:
                _user32.UnregisterHotKey(None, hid)
        self._callbacks.clear()

    def register(self, keystr, callback):
        """등록 성공 시 True. Windows가 아니거나 파싱/등록 실패 시 False."""
        if not IS_WIN:
            return False
        parsed = parse_hotkey(keystr)
        if not parsed:
            return False
        mods, vk = parsed
        hid = self._next_id
        if not _user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
            return False
        self._next_id += 1
        self._callbacks[hid] = callback
        return True

    def nativeEventFilter(self, eventType, message):
        if IS_WIN and bytes(eventType) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                cb = self._callbacks.get(msg.wParam)
                if cb is not None:
                    cb()
                    return True, 0
        return False, 0
