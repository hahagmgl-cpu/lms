#!/usr/bin/env python3
"""Smile Design Pro — exocad 치과 설계 보조 오버레이 메인 엔트리포인트"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from smile_overlay.config import OverlayState, load_autosave, save_autosave
from smile_overlay.overlay import SmileOverlay
from smile_overlay.panel import ControlPanel
from smile_overlay.hotkeys import GlobalHotkeys


def main():
    app = QApplication(sys.argv)

    # 상태 로드 (또는 새 상태)
    state = load_autosave() or OverlayState()

    # 오버레이 생성
    overlay = SmileOverlay(state)
    overlay.showFullScreen()

    # 컨트롤 패널 생성
    panel = ControlPanel(overlay, state)
    panel.show()

    # 캘리브레이션 완료 콜백
    def on_calib_done():
        panel.show_calib_done()

    overlay._on_calibration_done = on_calib_done

    # 전역 단축키 설정
    hotkeys = GlobalHotkeys()
    hotkeys.install(app)

    # 가이드별 단축키
    for key, label, *_ in __import__('smile_overlay.config', fromlist=['GUIDE_DEFS']).GUIDE_DEFS:
        hotkey_str = state.hotkeys.get(f"guide:{key}")
        if hotkey_str:
            hotkeys.register(hotkey_str, lambda k=key: toggle_guide(k))

    # 액션 단축키
    hotkeys.register(state.hotkeys.get("toggle_overlay", "Ctrl+Alt+H"), toggle_overlay)
    hotkeys.register(state.hotkeys.get("toggle_edit", "Ctrl+Alt+E"), lambda: overlay.toggle_edit())

    def toggle_guide(key):
        state.styles[key].visible = not state.styles[key].visible
        overlay.state_changed.emit()

    def toggle_overlay():
        overlay.setVisible(not overlay.isVisible())

    # 상태 저장 타이머
    def save_state():
        save_autosave(state)

    from PyQt6.QtCore import QTimer
    save_timer = QTimer()
    save_timer.timeout.connect(save_state)
    save_timer.start(5000)  # 5초마다 자동 저장

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
