"""메인 오버레이 윈도우 — 13개 가이드 렌더링 + 편집"""
import math
import ctypes
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath, QFont, QCursor
from smile_overlay.config import OverlayState

VK_MENU = 0x12
HANDLE_NONE = 0
HANDLE_FRAME_MOVE, HANDLE_FRAME_EDGE = 1, 2
HANDLE_GUIDE_MOVE = 10
HANDLE_ZENITH_PT = 20
HANDLE_ARC_CENTER = 30
HANDLE_ARC_END = 31
EDGE_GRAB = 8
LINE_GRAB = 10


class SmileOverlay(QWidget):
    """exocad 위 투명 오버레이. 모든 가이드는 프레임 기준 비율로 저장."""

    # 신호
    state_changed = pyqtSignal()

    def __init__(self, state: OverlayState):
        super().__init__()
        self.state = state

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        # 마우스 드래그 상태
        self._drag_handle = HANDLE_NONE
        self._drag_start = None
        self._drag_origin = None
        self._drag_frame_orig = None

        # 편집 모드
        self.edit_mode = False
        self.set_click_through(True)

        # Alt 이동 모드
        self._move_mode = False
        self._move_timer = QTimer()
        self._move_timer.timeout.connect(self._check_move_key)
        self._move_timer.start(50)

        # 캘리브레이션
        self.calibration_mode = False
        self.calib_points = []
        self.calib_markers = []

        # 호출 후 설정
        self._panel = None

    def set_click_through(self, enable):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enable)

    def _check_move_key(self):
        """Alt 키 감지"""
        try:
            alt_held = bool(ctypes.windll.user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        except Exception:
            return

        if alt_held and not self.edit_mode and not self.calibration_mode:
            if not self._move_mode:
                self._move_mode = True
                self.set_click_through(False)
                self.update()
        else:
            if self._move_mode and self._drag_handle == HANDLE_NONE:
                self._move_mode = False
                if not self.edit_mode:
                    self.set_click_through(True)
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                self.update()

    def toggle_edit(self):
        self.edit_mode = not self.edit_mode
        if not self.calibration_mode:
            self.set_click_through(not self.edit_mode)
        if self.edit_mode and self._panel:
            self._panel.raise_()
            self._panel.activateWindow()
        self.update()

    def start_calibration(self):
        self.calibration_mode = True
        self.calib_points = []
        self.calib_markers = []
        self.set_click_through(False)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.update()

    def cancel_calibration(self):
        self.calibration_mode = False
        self.calib_points = []
        self.calib_markers = []
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        if not self.edit_mode:
            self.set_click_through(True)
        self.update()

    def apply_calibration(self, p1, p2):
        """2점(좌우 견치 끝) → 프레임 자동 설정"""
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return

        left_pt = p1 if p1[0] < p2[0] else p2
        right_pt = p2 if p1[0] < p2[0] else p1

        lx = left_pt[0] / w
        rx = right_pt[0] / w
        cy = ((left_pt[1] + right_pt[1]) / 2) / h

        frame_w = rx - lx
        frame_h = frame_w * 0.50
        frame_x = lx
        frame_y = cy - frame_h * 0.5

        self.state.frame = [frame_x, frame_y, frame_w, frame_h]
        mid_x = (lx + rx) / 2
        frame_cx = frame_x + frame_w / 2
        self.state.midline_dx = mid_x - frame_cx

        self.state_changed.emit()
        self.update()

    # ---------- 좌표 변환 ----------
    def frame_rect_px(self):
        """프레임을 픽셀 좌표로"""
        w, h = self.width(), self.height()
        x, y, fw, fh = self.state.frame
        return QRectF(x*w, y*h, fw*w, fh*h)

    def midline_x_px(self):
        f = self.frame_rect_px()
        return f.center().x() + self.state.midline_dx * f.width()

    def incisal_y_px(self):
        f = self.frame_rect_px()
        return f.bottom() + self.state.incisal_dy * f.height()

    def contact_y_px(self):
        f = self.frame_rect_px()
        return f.top() + self.state.contact_dy * f.height()

    # ---------- 히트테스트 ----------
    def _hit_test(self, pos):
        f = self.frame_rect_px()
        x, y = pos.x(), pos.y()

        # 코너
        for (cx_, cy_) in [(f.left(), f.top()), (f.right(), f.top()),
                            (f.left(), f.bottom()), (f.right(), f.bottom())]:
            if abs(x - cx_) < EDGE_GRAB + 2 and abs(y - cy_) < EDGE_GRAB + 2:
                return HANDLE_FRAME_EDGE

        # 프레임 테두리
        in_y = f.top() - EDGE_GRAB <= y <= f.bottom() + EDGE_GRAB
        in_x = f.left() - EDGE_GRAB <= x <= f.right() + EDGE_GRAB
        if (in_y and (abs(x - f.left()) < EDGE_GRAB or abs(x - f.right()) < EDGE_GRAB)) or \
           (in_x and (abs(y - f.top()) < EDGE_GRAB or abs(y - f.bottom()) < EDGE_GRAB)):
            return HANDLE_FRAME_EDGE

        # 프레임 내부
        if f.contains(pos):
            return HANDLE_FRAME_MOVE

        return HANDLE_NONE

    # ---------- 마우스 이벤트 ----------
    def mousePressEvent(self, event):
        # 우클릭
        if event.button() == Qt.MouseButton.RightButton:
            if self.calibration_mode:
                self.cancel_calibration()
            elif self._move_mode:
                self._move_mode = False
                self._drag_handle = HANDLE_NONE
                self.set_click_through(True)
                self.update()
            elif self.edit_mode:
                self.toggle_edit()
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position()

        # 캘리브레이션 모드
        if self.calibration_mode:
            pt = (pos.x(), pos.y())
            self.calib_points.append(pt)
            self.calib_markers.append(pt)
            if len(self.calib_points) >= 2:
                self.apply_calibration(self.calib_points[0], self.calib_points[1])
                self.calibration_mode = False
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                if not self.edit_mode:
                    self.set_click_through(True)
            self.update()
            return

        # Alt 이동 모드
        if self._move_mode and not self.edit_mode:
            f = self.frame_rect_px()
            grab_rect = f.adjusted(-20, -20, 20, 20)
            if grab_rect.contains(pos):
                self._drag_handle = HANDLE_FRAME_MOVE
                self._drag_start = pos
                self._drag_frame_orig = list(self.state.frame)
            return

        if not self.edit_mode:
            return

        handle = self._hit_test(pos)
        if handle == HANDLE_NONE:
            event.ignore()
            return

        self._drag_handle = handle
        self._drag_start = pos
        self._drag_frame_orig = list(self.state.frame)

    def mouseMoveEvent(self, event):
        pos = event.position()

        # Alt 이동 모드
        if self._move_mode and not self.edit_mode:
            if self._drag_handle == HANDLE_FRAME_MOVE and self._drag_start:
                w, h = self.width(), self.height()
                dx = (pos.x() - self._drag_start.x()) / w
                dy = (pos.y() - self._drag_start.y()) / h
                orig = self._drag_frame_orig
                self.state.frame = [orig[0] + dx, orig[1] + dy, orig[2], orig[3]]
                self.state_changed.emit()
                self.update()
            else:
                f = self.frame_rect_px()
                grab_rect = f.adjusted(-20, -20, 20, 20)
                if grab_rect.contains(pos):
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                else:
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return

        if self.calibration_mode:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return

        if not self.edit_mode:
            return

        # 편집 모드: 드래그 중
        if self._drag_handle != HANDLE_NONE and self._drag_start:
            w, h = self.width(), self.height()
            dx = (pos.x() - self._drag_start.x()) / w
            dy = (pos.y() - self._drag_start.y()) / h

            if self._drag_handle == HANDLE_FRAME_MOVE:
                orig = self._drag_frame_orig
                self.state.frame = [orig[0] + dx, orig[1] + dy, orig[2], orig[3]]
            elif self._drag_handle == HANDLE_FRAME_EDGE:
                orig = self._drag_frame_orig
                x, y, fw, fh = orig
                new_w = fw + dx
                new_h = fh + dy
                if new_w > 0.02 and new_h > 0.02:
                    self.state.frame = [x, y, new_w, new_h]

            self.state_changed.emit()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            was_move_drag = (self._move_mode and self._drag_handle == HANDLE_FRAME_MOVE)
            self._drag_handle = HANDLE_NONE
            self._drag_start = None
            self._drag_frame_orig = None

            if was_move_drag:
                try:
                    alt_held = bool(ctypes.windll.user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                except Exception:
                    alt_held = False
                if not alt_held:
                    self._move_mode = False
                    if not self.edit_mode:
                        self.set_click_through(True)
                    self.update()

    # ---------- 키보드 이벤트 ----------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.calibration_mode:
                self.cancel_calibration()
            elif self.edit_mode:
                self.toggle_edit()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---------- 렌더링 ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = self.frame_rect_px()

        global_opacity = int(self.state.global_opacity * 2.55)
        cx = self.midline_x_px()

        # 캘리브레이션 모드
        if self.calibration_mode:
            p.fillRect(self.rect(), QColor(0, 0, 0, 60))
            p.setPen(QPen(QColor(255, 255, 0), 2))
            font = QFont("맑은 고딕", 18, QFont.Weight.Bold)
            p.setFont(font)
            remaining = 2 - len(self.calib_points)
            msg = ["🔵 좌측 견치 끝점", "🔴 우측 견치 끝점", "✅ 캘리브레이션 완료!"][2 - remaining]
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, msg)

            for i, pt in enumerate(self.calib_markers):
                color = QColor(0, 150, 255) if i == 0 else QColor(255, 80, 80)
                p.setPen(QPen(color, 3))
                p.setBrush(color)
                p.drawEllipse(QPointF(pt[0], pt[1]), 8, 8)
                p.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
                p.drawLine(int(pt[0]) - 30, int(pt[1]), int(pt[0]) + 30, int(pt[1]))
                p.drawLine(int(pt[0]), int(pt[1]) - 30, int(pt[0]), int(pt[1]) + 30)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # Alt 이동 모드
        if self._move_mode and not self.edit_mode and not self.calibration_mode:
            p.setPen(QPen(QColor(100, 200, 255, 180), 2, Qt.PenStyle.DashLine))
            p.drawRect(f.adjusted(-5, -5, 5, 5))
            p.setPen(QPen(QColor(100, 200, 255, 220), 1))
            hint_font = QFont("맑은 고딕", 12, QFont.Weight.Bold)
            p.setFont(hint_font)
            p.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                "🔀 Alt 누르고 드래그  |  마친 후 Alt 놓기"
            )

        # 편집 모드
        if self.edit_mode and not self.calibration_mode:
            p.fillRect(self.rect(), QColor(0, 0, 0, 30))
            p.setPen(QPen(QColor(255, 255, 100, 200), 1))
            hint_font = QFont("맑은 고딕", 12, QFont.Weight.Bold)
            p.setFont(hint_font)
            p.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                "✏️ 편집 모드  |  프레임 드래그 또는 ESC 종료"
            )

            p.setPen(QPen(QColor(255, 255, 0, 150), 1, Qt.PenStyle.DashLine))
            p.drawRect(f)
            handle_size = 6
            p.setBrush(QColor(255, 255, 0, 180))
            for (hx, hy) in [(f.left(), f.top()), (f.right(), f.top()),
                              (f.left(), f.bottom()), (f.right(), f.bottom())]:
                p.drawRect(QRectF(hx - handle_size, hy - handle_size,
                                  handle_size * 2, handle_size * 2))
            p.setBrush(Qt.BrushStyle.NoBrush)

        # ---------- 13개 가이드 렌더링 ----------

        # 1. 정중선
        if self.state.styles["midline"].visible:
            style = self.state.styles["midline"]
            color = QColor(style.color)
            color.setAlpha(int(global_opacity * style.opacity / 100))
            p.setPen(QPen(color, style.width * self.state.global_width))
            p.drawLine(int(cx), int(f.top() - 40), int(cx), int(f.bottom() + 40))

        # 2. 스마일 아크
        if self.state.styles["smile_arc"].visible:
            style = self.state.styles["smile_arc"]
            color = QColor(style.color)
            color.setAlpha(int(global_opacity * style.opacity / 100))
            p.setPen(QPen(color, style.width * self.state.global_width))
            path = QPainterPath()
            arc_bottom = f.bottom() + self.state.arc_depth * f.height()
            path.moveTo(f.left() - 30, f.bottom() - f.height() * self.state.arc_end_rise)
            path.quadTo(cx, arc_bottom,
                        f.right() + 30, f.bottom() - f.height() * self.state.arc_end_rise)
            p.drawPath(path)

        # 3. 절단연
        if self.state.styles["incisal"].visible:
            style = self.state.styles["incisal"]
            color = QColor(style.color)
            color.setAlpha(int(global_opacity * style.opacity / 100))
            p.setPen(QPen(color, style.width * self.state.global_width))
            iy = self.incisal_y_px()
            p.drawLine(int(f.left() - 20), int(iy), int(f.right() + 20), int(iy))

        # 4. 황금비율
        if self.state.styles["golden"].visible:
            self._draw_golden_ratio(p, f, cx, global_opacity)

        # 5. 폭/길이 비율 박스
        if self.state.styles["ratio_box"].visible:
            self._draw_ratio_boxes(p, f, global_opacity)

        # 6. 대칭
        if self.state.styles["symmetry"].visible:
            self._draw_symmetry(p, f, global_opacity)

        # 7. 치은 정점
        if self.state.styles["zenith"].visible:
            self._draw_zenith(p, f, global_opacity)

        # 8. 치은 라인 곡선
        if self.state.styles["gingival_curve"].visible:
            self._draw_gingival_curve(p, f, global_opacity)

        # 9. 치축 경사
        if self.state.styles["axial"].visible:
            self._draw_axial(p, f, global_opacity)

        # 10. 접촉점
        if self.state.styles["contact"].visible:
            style = self.state.styles["contact"]
            color = QColor(style.color)
            color.setAlpha(int(global_opacity * style.opacity / 100))
            p.setPen(QPen(color, style.width * self.state.global_width, Qt.PenStyle.DashLine))
            cty = self.contact_y_px()
            p.drawLine(int(f.left()), int(cty), int(f.right()), int(cty))

        # 11. 절단 엠브레저
        if self.state.styles["embrasure"].visible:
            self._draw_embrasure(p, f, global_opacity)

        # 12. 협측 회랑
        if self.state.styles["corridor"].visible:
            style = self.state.styles["corridor"]
            color = QColor(style.color)
            color.setAlpha(int(global_opacity * style.opacity / 100))
            p.setPen(QPen(color, style.width * self.state.global_width))
            p.setBrush(QColor(int(color.red()), int(color.green()), int(color.blue()), 40))
            cw = f.width() * self.state.corridor_w
            p.drawRect(QRectF(f.left() - cw, f.top(), cw, f.height()))
            p.drawRect(QRectF(f.right(), f.top(), cw, f.height()))
            p.setBrush(Qt.BrushStyle.NoBrush)

        # 13. 치아 사이즈 정보
        if self.state.styles["tooth_size"].visible:
            self._draw_tooth_info(p, f, global_opacity)

        p.end()

    def _draw_golden_ratio(self, p, f, cx, global_opacity):
        """황금비율: 1.618 : 1 : 0.618"""
        style = self.state.styles["golden"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width, Qt.PenStyle.DotLine))

        phi = 1.618
        f_w = f.width()
        central_w = self.state.golden_central * f_w
        lateral_w = central_w / phi
        canine_w = lateral_w * 0.618

        edges = [cx - canine_w - lateral_w - central_w,
                 cx - lateral_w - central_w,
                 cx - central_w,
                 cx,
                 cx + central_w,
                 cx + central_w + lateral_w,
                 cx + central_w + lateral_w + canine_w]

        for x in edges:
            p.drawLine(int(x), int(f.top()), int(x), int(f.bottom()))

    def _draw_ratio_boxes(self, p, f, global_opacity):
        """폭/길이 비율 박스"""
        style = self.state.styles["ratio_box"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width))

        seg_w = f.width() / 6
        for i in range(6):
            bx = f.left() + seg_w * i
            bw = seg_w * 0.9
            bh = bw / (self.state.ratio_wl / 100.0)
            p.drawRect(QRectF(bx + (seg_w - bw) / 2, f.top(), bw, min(bh, f.height())))

    def _draw_symmetry(self, p, f, global_opacity):
        """대칭 가이드"""
        style = self.state.styles["symmetry"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width, Qt.PenStyle.DashLine))

        seg_w = f.width() / 6
        for i in range(1, 6):
            x = f.left() + seg_w * i
            p.drawLine(int(x), int(f.top() - 10), int(x), int(f.bottom() + 10))

    def _draw_zenith(self, p, f, global_opacity):
        """치은 정점 (개별 조절 가능)"""
        style = self.state.styles["zenith"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width))
        p.setBrush(color)

        seg_w = f.width() / 6
        for i in range(6):
            seg_x = f.left() + seg_w * i
            zx = seg_x + seg_w * self.state.zenith_dx[i]
            zy = f.top() + self.state.zenith_dy[i] * f.height()
            p.drawEllipse(QPointF(zx, zy), 4, 4)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_gingival_curve(self, p, f, global_opacity):
        """제니스 점들을 잇는 치은 곡선"""
        style = self.state.styles["gingival_curve"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width))

        path = QPainterPath()
        seg_w = f.width() / 6
        pts = []
        for i in range(6):
            seg_x = f.left() + seg_w * i
            zx = seg_x + seg_w * self.state.zenith_dx[i]
            zy = f.top() + self.state.zenith_dy[i] * f.height()
            pts.append(QPointF(zx, zy))

        if len(pts) >= 2:
            path.moveTo(pts[0])
            for i in range(1, len(pts)):
                path.lineTo(pts[i])
            p.drawPath(path)

    def _draw_axial(self, p, f, global_opacity):
        """치축 경사"""
        style = self.state.styles["axial"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width))

        seg_w = f.width() / 6
        for i in range(3):
            # 좌측
            seg_x = f.left() + seg_w * i
            tooth_cx = seg_x + seg_w / 2
            dx = seg_w * self.state.axial_tilt[2 - i]
            p.drawLine(int(tooth_cx - dx), int(f.top()),
                       int(tooth_cx + dx), int(f.bottom()))

            # 우측
            seg_x = f.left() + seg_w * (i + 3)
            tooth_cx = seg_x + seg_w / 2
            p.drawLine(int(tooth_cx + dx), int(f.top()),
                       int(tooth_cx - dx), int(f.bottom()))

    def _draw_embrasure(self, p, f, global_opacity):
        """절단 엠브레저 (V자)"""
        style = self.state.styles["embrasure"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(QPen(color, style.width * self.state.global_width))

        seg_w = f.width() / 6
        for i in range(5):
            x1 = f.left() + seg_w * (i + 1) - 8
            x2 = f.left() + seg_w * (i + 1) + 8
            y_top = f.top()
            y_bot = f.top() + f.height() * 0.2 * (i % 2 + 1)
            p.drawLine(int(x1), int(y_top), int(f.left() + seg_w * (i + 1)), int(y_bot))
            p.drawLine(int(x2), int(y_top), int(f.left() + seg_w * (i + 1)), int(y_bot))

    def _draw_tooth_info(self, p, f, global_opacity):
        """치아 크기 정보"""
        style = self.state.styles["tooth_size"]
        color = QColor(style.color)
        color.setAlpha(int(global_opacity * style.opacity / 100))
        p.setPen(color)

        font = QFont("맑은 고딕", 8)
        p.setFont(font)
        seg_w = f.width() / 6
        tooth_names = ["#13", "#12", "#11", "#21", "#22", "#23"]

        for i, name in enumerate(tooth_names):
            x = f.left() + seg_w * i + seg_w / 2
            p.drawText(int(x - 15), int(f.top() - 15), 30, 12,
                      Qt.AlignmentFlag.AlignCenter, name)
