"""설정 / 상태 / 프리셋 관리.

모든 가이드 위치는 프레임(치아 영역) 기준 '비율'로 저장된다.
따라서 프레임을 이동/리사이즈하거나 캘리브레이션으로 크기가 바뀌어도
모든 가이드 선이 유기적으로 함께 움직인다.
"""
import json
import os
from dataclasses import asdict, dataclass, field

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".smile_overlay")
PRESET_DIR = os.path.join(CONFIG_DIR, "presets")
AUTOSAVE_PATH = os.path.join(CONFIG_DIR, "last_session.json")


@dataclass
class GuideStyle:
    color: str = "#FFFFFF"
    width: float = 2.0
    opacity: int = 100      # 개별 불투명도(%) — 전역 불투명도와 곱해짐
    visible: bool = False


# (key, 라벨, 기본색, 기본굵기, 기본표시, 기본단축키, 설명)
GUIDE_DEFS = [
    ("midline",        "① 정중선 (Midline)",      "#FF3B3B", 2.5, True,
     "Ctrl+Alt+1", "얼굴/치아 정중선. 선 또는 상하 핸들 드래그로 좌우 이동"),
    ("smile_arc",      "② 스마일 아크",           "#00AAFF", 3.0, True,
     "Ctrl+Alt+2", "하순 곡선. 중앙 핸들=깊이, 양끝 핸들=끝 높이 조절"),
    ("incisal",        "③ 절단연 (Incisal)",      "#00E676", 2.5, True,
     "Ctrl+Alt+3", "절단연 수평선. 상하 드래그"),
    ("golden",         "④ 황금비율",              "#FFC400", 1.5, False,
     "Ctrl+Alt+4", "1.618 : 1 : 0.618 분할. 하단 노란 핸들로 중절치 폭 조절"),
    ("ratio_box",      "⑤ 폭/길이 비율 박스",     "#00E5FF", 1.5, False,
     "Ctrl+Alt+5", "치관 W/L 비율 박스 (조정 탭에서 % 변경 가능, 기본 80%)"),
    ("symmetry",       "⑥ 대칭 가이드",           "#FF4DFF", 1.5, False,
     "Ctrl+Alt+6", "치아 경계 대칭 세로선"),
    ("zenith",         "⑦ 치은 정점 (Zenith)",    "#FF5252", 2.5, False,
     "Ctrl+Alt+7", "치아별 개별 드래그 가능 — 원심 치우침 기본값 적용"),
    ("gingival_curve", "⑧ 치은 라인 곡선",        "#FF8A80", 2.0, False,
     "Ctrl+Alt+8", "제니스 점들을 잇는 치은 윤곽 곡선 (제니스 이동 시 함께 변형)"),
    ("axial",          "⑨ 치축 경사 (Axial)",     "#FF9100", 2.0, False,
     "Ctrl+Alt+9", "상단(치경부) 핸들 드래그로 기울기 조절 — 좌우 대칭 유지"),
    ("contact",        "⑩ 접촉점 (Contact)",      "#FFFFFF", 1.5, False,
     "Ctrl+Alt+0", "접촉점 높이선 + 인접면 접촉 마커"),
    ("embrasure",      "⑪ 절단 엠브레저",         "#B388FF", 2.0, False,
     "Ctrl+Alt+-", "절단연 V자 함몰 — 원심으로 갈수록 깊어짐"),
    ("corridor",       "⑫ 협측 회랑 (Corridor)",  "#7C4DFF", 1.5, False,
     "Ctrl+Alt+=", "버컬 코리도 영역. 바깥 핸들로 폭 조절"),
    ("tooth_size",     "⑬ 치아 사이즈 정보",      "#FFD54F", 1.0, False,
     "Ctrl+Alt+T", "평균 근원심폭 / 치관길이(mm), W/L%"),
]

# (action key, 라벨, 기본 단축키)
ACTION_DEFS = [
    ("toggle_overlay", "오버레이 전체 ON/OFF",     "Ctrl+Alt+H"),
    ("toggle_edit",    "편집 모드 토글",           "Ctrl+Alt+E"),
    ("calibrate",      "캐닌 2점 캘리브레이션",    "Ctrl+Alt+C"),
    ("opacity_up",     "전체 불투명도 +",          "Ctrl+Alt+Up"),
    ("opacity_down",   "전체 불투명도 -",          "Ctrl+Alt+Down"),
    ("width_up",       "전체 선 굵기 +",           "Ctrl+Alt+Right"),
    ("width_down",     "전체 선 굵기 -",           "Ctrl+Alt+Left"),
]

GUIDE_KEYS = [g[0] for g in GUIDE_DEFS]


def default_styles():
    return {
        key: GuideStyle(color=color, width=width, visible=visible)
        for (key, _label, color, width, visible, _hk, _desc) in GUIDE_DEFS
    }


def default_hotkeys():
    hk = {f"guide:{key}": hkey for (key, _l, _c, _w, _v, hkey, _d) in GUIDE_DEFS}
    hk.update({action: key for (action, _label, key) in ACTION_DEFS})
    return hk


# 위치(기하) 관련 필드 — '위치 초기화'에서 이 값들만 리셋
_GEOMETRY_FIELDS = (
    "frame", "midline_dx", "incisal_dy", "contact_dy",
    "arc_depth", "arc_end_rise", "golden_central", "corridor_w",
    "zenith_dx", "zenith_dy", "axial_tilt",
)

_SIMPLE_FIELDS = _GEOMETRY_FIELDS + (
    "ratio_wl", "use_proportional", "global_opacity", "global_width",
)


@dataclass
class OverlayState:
    # 프레임: 화면 비율 기준 [x, y, w, h]
    frame: list = field(default_factory=lambda: [0.30, 0.35, 0.40, 0.20])
    # 정중선: 프레임 중심 기준, 프레임 폭 대비 비율
    midline_dx: float = 0.0
    # 절단연: 프레임 하단 기준, 프레임 높이 대비 비율
    incisal_dy: float = 0.0
    # 접촉점 높이: 프레임 상단 기준, 프레임 높이 대비 비율
    contact_dy: float = 0.25
    # 스마일 아크: 중앙 깊이 / 양끝 상승량 (프레임 높이 대비)
    arc_depth: float = 0.25
    arc_end_rise: float = 0.15
    # 황금비율: 중절치 한쪽 폭 (프레임 폭 대비)
    golden_central: float = 0.25
    # 협측 회랑 폭 (프레임 폭 대비)
    corridor_w: float = 0.12
    # 치관 폭/길이 비율 (%)
    ratio_wl: float = 80.0
    # 치은 정점: 치아별 (세그먼트 폭 대비 x, 프레임 높이 대비 y)
    # 순서: [#13, #12, #11, #21, #22, #23] — 원심 치우침 기본값
    zenith_dx: list = field(default_factory=lambda: [0.35, 0.40, 0.42, 0.58, 0.60, 0.65])
    zenith_dy: list = field(default_factory=lambda: [0.0] * 6)
    # 치축 경사: [중절치, 측절치, 견치] (세그먼트 폭 대비 기울기)
    axial_tilt: list = field(default_factory=lambda: [0.03, 0.06, 0.10])
    # 치아 폭 분할: True=평균 근원심폭 비례, False=균등 6분할
    use_proportional: bool = True
    # 전역 표시 설정
    global_opacity: int = 80    # %
    global_width: float = 1.0   # 굵기 배율
    styles: dict = field(default_factory=default_styles)
    hotkeys: dict = field(default_factory=default_hotkeys)

    # ---------- 직렬화 ----------
    def to_dict(self):
        d = {k: getattr(self, k) for k in _SIMPLE_FIELDS}
        d["styles"] = {k: asdict(v) for k, v in self.styles.items()}
        d["hotkeys"] = dict(self.hotkeys)
        d["version"] = 2
        return d

    @classmethod
    def from_dict(cls, d):
        st = cls()
        for k in _SIMPLE_FIELDS:
            if k in d:
                setattr(st, k, d[k])
        # 리스트 길이 보정
        defaults = cls()
        if not isinstance(st.frame, list) or len(st.frame) != 4:
            st.frame = defaults.frame
        if not isinstance(st.zenith_dx, list) or len(st.zenith_dx) != 6:
            st.zenith_dx = defaults.zenith_dx
        if not isinstance(st.zenith_dy, list) or len(st.zenith_dy) != 6:
            st.zenith_dy = defaults.zenith_dy
        if not isinstance(st.axial_tilt, list) or len(st.axial_tilt) != 3:
            st.axial_tilt = defaults.axial_tilt

        for key, sd in (d.get("styles") or {}).items():
            gs = st.styles.get(key)
            if gs is not None and isinstance(sd, dict):
                gs.color = str(sd.get("color", gs.color))
                gs.width = float(sd.get("width", gs.width))
                gs.opacity = int(sd.get("opacity", gs.opacity))
                gs.visible = bool(sd.get("visible", gs.visible))

        for key, val in (d.get("hotkeys") or {}).items():
            if key in st.hotkeys:
                st.hotkeys[key] = str(val)
        return st

    def reset_geometry(self):
        """프레임/가이드 위치만 기본값으로 (스타일·단축키는 유지)"""
        defaults = OverlayState()
        for k in _GEOMETRY_FIELDS:
            setattr(self, k, getattr(defaults, k))


# ---------- 프리셋 파일 관리 ----------
def _ensure_dirs():
    os.makedirs(PRESET_DIR, exist_ok=True)


def list_presets():
    _ensure_dirs()
    names = [
        os.path.splitext(f)[0]
        for f in os.listdir(PRESET_DIR)
        if f.lower().endswith(".json")
    ]
    return sorted(names)


def _preset_path(name):
    safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
    return os.path.join(PRESET_DIR, f"{safe}.json")


def save_preset(name, state):
    _ensure_dirs()
    with open(_preset_path(name), "w", encoding="utf-8") as fp:
        json.dump(state.to_dict(), fp, ensure_ascii=False, indent=2)


def load_preset(name):
    with open(_preset_path(name), encoding="utf-8") as fp:
        return OverlayState.from_dict(json.load(fp))


def delete_preset(name):
    path = _preset_path(name)
    if os.path.exists(path):
        os.remove(path)


def save_autosave(state):
    _ensure_dirs()
    try:
        with open(AUTOSAVE_PATH, "w", encoding="utf-8") as fp:
            json.dump(state.to_dict(), fp, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_autosave():
    try:
        with open(AUTOSAVE_PATH, encoding="utf-8") as fp:
            return OverlayState.from_dict(json.load(fp))
    except (OSError, ValueError):
        return None
