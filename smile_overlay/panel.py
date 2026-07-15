"""컨트롤 패널 UI — 13개 가이드 + 단축키 + 프리셋"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox, QSlider,
    QLabel, QPushButton, QTabWidget, QScrollArea, QColorDialog, QSpinBox,
    QDoubleSpinBox, QListWidget, QListWidgetItem, QInputDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from smile_overlay.config import OverlayState, GUIDE_DEFS, list_presets, save_preset, load_preset, delete_preset
from smile_overlay.theme import DARK_QSS


class ControlPanel(QWidget):
    def __init__(self, overlay, state: OverlayState):
        super().__init__()
        self.ov = overlay
        self.state = state
        self._updating = False

        self.setWindowTitle("Smile Design Pro v2.0")
        self.setStyleSheet(DARK_QSS)
        self.setFixedWidth(350)

        # 레이아웃
        main_layout = QVBoxLayout()

        # ── 헤더 ──
        title = QLabel("Smile Design Pro")
        title.setObjectName("appTitle")
        subtitle = QLabel("exocad 치과 설계 보조 오버레이")
        subtitle.setObjectName("appSubtitle")
        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # ── 탭 ──
        tabs = QTabWidget()
        tabs.addTab(self._make_guides_tab(), "📋 가이드")
        tabs.addTab(self._make_edit_tab(), "✏️ 편집")
        tabs.addTab(self._make_style_tab(), "🎨 스타일")
        tabs.addTab(self._make_hotkey_tab(), "⌨️ 단축키")
        tabs.addTab(self._make_preset_tab(), "💾 프리셋")
        main_layout.addWidget(tabs)

        # ── 상태 표시 ──
        self.status = QLabel("대기 중")
        self.status.setObjectName("statusBar")
        main_layout.addWidget(self.status)

        self.setLayout(main_layout)

        # 신호 연결
        self.ov.state_changed.connect(self._on_state_changed)

    # ────────────── 탭 1: 가이드 목록 ──────────────
    def _make_guides_tab(self):
        w = QWidget()
        layout = QVBoxLayout()

        calib_gb = QGroupBox("📐 캘리브레이션")
        calib_layout = QVBoxLayout()
        self.btn_calib = QPushButton("🎯 캐닌 2점 캘리브레이션")
        self.btn_calib.setObjectName("primaryBtn")
        self.btn_calib.clicked.connect(self._start_calibration)
        calib_layout.addWidget(self.btn_calib)
        self.lbl_calib_status = QLabel("준비됨")
        self.lbl_calib_status.setStyleSheet("color: #9aa4b2; font-size: 10px;")
        calib_layout.addWidget(self.lbl_calib_status)
        calib_gb.setLayout(calib_layout)
        layout.addWidget(calib_gb)

        guides_gb = QGroupBox("13가지 가이드 ON/OFF")
        guides_layout = QVBoxLayout()
        self._guide_checks = {}
        for key, label, *_ in GUIDE_DEFS:
            cb = QCheckBox(label)
            cb.setChecked(self.state.styles[key].visible)
            cb.stateChanged.connect(lambda s, k=key: self._toggle_guide(k, s))
            guides_layout.addWidget(cb)
            self._guide_checks[key] = cb
        guides_gb.setLayout(guides_layout)
        scroll = QScrollArea()
        scroll.setWidget(guides_gb)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        w.setLayout(layout)
        return w

    def _start_calibration(self):
        self.ov.start_calibration()
        self.btn_calib.setEnabled(False)
        self.lbl_calib_status.setText("🔵 좌측 견치 끝점 클릭...")
        self.lbl_calib_status.setStyleSheet("color: #0096FF; font-weight: bold;")

    def _toggle_guide(self, key, state):
        self.state.styles[key].visible = bool(state)
        self.ov.state_changed.emit()

    # ────────────── 탭 2: 편집 ──────────────
    def _make_edit_tab(self):
        w = QWidget()
        layout = QVBoxLayout()

        # 편집 모드 토글
        self.btn_edit = QPushButton("편집 모드 켜기")
        self.btn_edit.setCheckable(True)
        self.btn_edit.setObjectName("primaryBtn")
        self.btn_edit.clicked.connect(self._toggle_edit)
        layout.addWidget(self.btn_edit)

        # Alt 이동 모드
        alt_info = QLabel("🔀 Alt 누르고 드래그\n프레임을 즉시 이동\n(편집 모드 불필요)")
        alt_info.setStyleSheet("color: #4AADFF; font-size: 10px; padding: 8px; background: #232a32; border-radius: 5px;")
        alt_info.setWordWrap(True)
        layout.addWidget(alt_info)

        # 편집 모드 힌트
        hint = QLabel(
            "편집 모드 활성화 후:\n"
            "• 프레임 경계 드래그 → 크기 조절\n"
            "• 프레임 중심 드래그 → 위치 이동\n"
            "• 각 가이드 선 핸들 → 개별 위치 조절"
        )
        hint.setStyleSheet("color: #9aa4b2; font-size: 9px; padding: 8px; background: #14181d; border-radius: 5px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 초기화 버튼
        btn_reset = QPushButton("🔄 위치 초기화")
        btn_reset.clicked.connect(self._reset_positions)
        layout.addWidget(btn_reset)

        layout.addStretch()
        w.setLayout(layout)
        return w

    def _toggle_edit(self):
        self.ov.toggle_edit()
        self.btn_edit.setChecked(self.ov.edit_mode)
        self.btn_edit.setText("편집 모드 닫기" if self.ov.edit_mode else "편집 모드 켜기")

    def _reset_positions(self):
        if QMessageBox.question(self, "확인", "모든 위치를 초기화하시겠습니까?") == QMessageBox.StandardButton.Yes:
            self.state.reset_geometry()
            self.ov.state_changed.emit()
            self.status.setText("✓ 위치 초기화됨")

    # ────────────── 탭 3: 스타일 (색상, 굵기, 투명도) ──────────────
    def _make_style_tab(self):
        w = QWidget()
        layout = QVBoxLayout()

        # 전역 설정
        global_gb = QGroupBox("전역 설정")
        global_layout = QVBoxLayout()

        # 전역 불투명도
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("전체 불투명도"))
        opacity_slider = QSlider(Qt.Orientation.Horizontal)
        opacity_slider.setRange(10, 100)
        opacity_slider.setValue(self.state.global_opacity)
        opacity_slider.valueChanged.connect(lambda v: setattr(self.state, 'global_opacity', v) or self.ov.update())
        opacity_layout.addWidget(opacity_slider)
        self.lbl_opacity = QLabel(f"{self.state.global_opacity}%")
        opacity_slider.valueChanged.connect(lambda v: self.lbl_opacity.setText(f"{v}%"))
        opacity_layout.addWidget(self.lbl_opacity)
        global_layout.addLayout(opacity_layout)

        # 전역 굵기
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("전체 선 굵기"))
        width_spinner = QDoubleSpinBox()
        width_spinner.setRange(0.5, 3.0)
        width_spinner.setSingleStep(0.1)
        width_spinner.setValue(self.state.global_width)
        width_spinner.valueChanged.connect(lambda v: setattr(self.state, 'global_width', v) or self.ov.update())
        width_layout.addWidget(width_spinner)
        global_layout.addLayout(width_layout)

        global_gb.setLayout(global_layout)
        layout.addWidget(global_gb)

        # 개별 가이드 스타일
        style_gb = QGroupBox("개별 가이드 스타일")
        style_scroll = QScrollArea()
        style_scroll.setWidgetResizable(True)
        style_widget = QWidget()
        style_layout = QVBoxLayout()

        self._color_btns = {}
        self._width_spins = {}
        self._opacity_sliders = {}

        for key, label, *_ in GUIDE_DEFS:
            guide_layout = QVBoxLayout()
            title = QLabel(label)
            title.setFont(QFont("맑은 고딕", 10, QFont.Weight.Bold))
            guide_layout.addWidget(title)

            # 색상 + 굵기
            color_width_layout = QHBoxLayout()
            btn_color = QPushButton("색상")
            btn_color.setMaximumWidth(60)
            btn_color.clicked.connect(lambda _, k=key: self._pick_color(k))
            color_width_layout.addWidget(btn_color)
            self._color_btns[key] = btn_color

            spin_width = QDoubleSpinBox()
            spin_width.setRange(0.5, 4.0)
            spin_width.setSingleStep(0.1)
            spin_width.setValue(self.state.styles[key].width)
            spin_width.valueChanged.connect(lambda v, k=key: setattr(self.state.styles[k], 'width', v) or self.ov.update())
            color_width_layout.addWidget(QLabel("굵기"))
            color_width_layout.addWidget(spin_width)
            self._width_spins[key] = spin_width
            guide_layout.addLayout(color_width_layout)

            # 투명도
            opacity_layout = QHBoxLayout()
            opacity_layout.addWidget(QLabel("투명도"))
            opacity_slider = QSlider(Qt.Orientation.Horizontal)
            opacity_slider.setRange(10, 100)
            opacity_slider.setValue(self.state.styles[key].opacity)
            opacity_slider.valueChanged.connect(lambda v, k=key: setattr(self.state.styles[k], 'opacity', v) or self.ov.update())
            opacity_layout.addWidget(opacity_slider)
            self._opacity_sliders[key] = opacity_slider
            guide_layout.addLayout(opacity_layout)

            style_layout.addLayout(guide_layout)

        style_widget.setLayout(style_layout)
        style_scroll.setWidget(style_widget)
        layout.addWidget(style_scroll)

        w.setLayout(layout)
        return w

    def _pick_color(self, key):
        color = QColorDialog.getColor(
            QColor(self.state.styles[key].color),
            self, "색상 선택"
        )
        if color.isValid():
            self.state.styles[key].color = color.name()
            self._color_btns[key].setStyleSheet(f"background-color: {color.name()};")
            self.ov.update()

    # ────────────── 탭 4: 단축키 ──────────────
    def _make_hotkey_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("가이드별 단축키 (클릭해서 재설정)"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        hotkey_widget = QWidget()
        hotkey_layout = QVBoxLayout()

        for key, label, *_ in GUIDE_DEFS:
            hk_layout = QHBoxLayout()
            hk_layout.addWidget(QLabel(label))
            hotkey_text = QLabel(self.state.hotkeys.get(f"guide:{key}", "미설정"))
            hotkey_text.setStyleSheet("color: #FFD54F; font-weight: bold;")
            hk_layout.addWidget(hotkey_text)
            btn = QPushButton("변경")
            btn.setMaximumWidth(50)
            hk_layout.addWidget(btn)
            hotkey_layout.addLayout(hk_layout)

        hotkey_widget.setLayout(hotkey_layout)
        scroll.setWidget(hotkey_widget)
        layout.addWidget(scroll)

        w.setLayout(layout)
        return w

    # ────────────── 탭 5: 프리셋 ──────────────
    def _make_preset_tab(self):
        w = QWidget()
        layout = QVBoxLayout()

        # 저장
        save_layout = QHBoxLayout()
        self.txt_preset_name = QLabel()
        save_layout.addWidget(QLabel("프리셋명:"))
        save_layout.addWidget(self.txt_preset_name)
        btn_save = QPushButton("💾 저장")
        btn_save.clicked.connect(self._save_preset)
        save_layout.addWidget(btn_save)
        layout.addLayout(save_layout)

        # 프리셋 목록
        layout.addWidget(QLabel("저장된 프리셋:"))
        self.preset_list = QListWidget()
        self._refresh_presets()
        layout.addWidget(self.preset_list)

        # 불러오기/삭제
        btn_layout = QHBoxLayout()
        btn_load = QPushButton("📂 불러오기")
        btn_load.clicked.connect(self._load_preset)
        btn_delete = QPushButton("🗑️ 삭제")
        btn_delete.clicked.connect(self._delete_preset)
        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_delete)
        layout.addLayout(btn_layout)

        w.setLayout(layout)
        return w

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "프리셋 저장", "프리셋명:")
        if ok and name.strip():
            save_preset(name.strip(), self.state)
            self._refresh_presets()
            self.status.setText(f"✓ '{name}' 저장됨")

    def _load_preset(self):
        item = self.preset_list.currentItem()
        if item:
            preset_name = item.text()
            loaded_state = load_preset(preset_name)
            self.state.__dict__.update(loaded_state.__dict__)
            self.ov.state = self.state
            self.ov.state_changed.emit()
            self.status.setText(f"✓ '{preset_name}' 불러옴")

    def _delete_preset(self):
        item = self.preset_list.currentItem()
        if item:
            preset_name = item.text()
            delete_preset(preset_name)
            self._refresh_presets()
            self.status.setText(f"✓ '{preset_name}' 삭제됨")

    def _refresh_presets(self):
        self.preset_list.clear()
        for name in list_presets():
            self.preset_list.addItem(QListWidgetItem(name))

    # ────────────── 신호 ──────────────
    def _on_state_changed(self):
        if not self._updating:
            self._updating = True
            # UI 상태 동기화
            for key, cb in self._guide_checks.items():
                cb.blockSignals(True)
                cb.setChecked(self.state.styles[key].visible)
                cb.blockSignals(False)
            self._updating = False

    def show_calib_done(self):
        self.btn_calib.setEnabled(True)
        self.lbl_calib_status.setText("✅ 캘리브레이션 완료!")
        self.lbl_calib_status.setStyleSheet("color: #00AA00; font-weight: bold;")
        self.status.setText("✓ 캘리브레이션 성공")
