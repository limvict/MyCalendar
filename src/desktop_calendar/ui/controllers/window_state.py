# coding: utf-8
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QWidget, QApplication
from desktop_calendar.config.manager import ConfigManager


class WindowStateManager:
    """窗口状态管理：拖拽、置顶、透明度、位置记忆、边界限制。"""

    def __init__(self, window: QWidget, config: ConfigManager):
        self.window = window
        self.config = config
        self._drag_pos = QPoint()
        self._is_dragging = False

        opacity = config.get("opacity", 0.92)
        self.window.setWindowOpacity(opacity)

        if config.get("topmost", False):
            self.set_topmost(True)

        px = config.get("pos_x")
        py = config.get("pos_y")
        if px is not None and py is not None:
            self.window.move(px, py)

    def set_opacity(self, value: float):
        value = max(0.0, min(1.0, float(value)))
        self.window.setWindowOpacity(value)

    def set_topmost(self, enable: bool):
        """
        切换置顶。

        必须记录 was_minimized：无条件 show() 会把最小化状态恢复为正常
        显示，用户从托盘勾选"置顶"时隐藏（最小化）窗口会被拉出来。
        """
        was_visible = self.window.isVisible()
        was_minimized = self.window.isMinimized()
        geo = (self.window.saveGeometry()
           if (was_visible and not was_minimized) else None)
        self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enable)
        if was_visible:
            if was_minimized:
                self.window.showMinimized()
            else:
                self.window.show()
            if geo is not None:
                self.window.restoreGeometry(geo)

    def mouse_press_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (event.globalPosition().toPoint()
                              - self.window.frameGeometry().topLeft())
            self._is_dragging = True
            event.accept()

    def mouse_move_event(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._is_dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_pos

            # 用窗口中心所在屏幕判定，避免拖动过程中鼠标短暂越界
            # 或快速跨屏导致边界基准跳变。
            center = QPoint(
                new_pos.x() + self.window.width() // 2,
                new_pos.y() + self.window.height() // 2,
            )
            screen = QApplication.screenAt(center) or QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                # X / Y 各自独立夹取，且各自在"约束区间非法"时跳过，
                # 语义对称：屏幕装不下窗口时不做无意义夹取，
                # 而不是把窗口推到某个越界坐标。
                lo_x = geo.left() + 100 - self.window.width()
                hi_x = geo.right() - 100
                if lo_x <= hi_x:
                    new_pos.setX(max(lo_x, min(new_pos.x(), hi_x)))

                lo_y = geo.top() + 100 - self.window.height()
                hi_y = geo.bottom() - 100
                if lo_y <= hi_y:
                    new_pos.setY(max(lo_y, min(new_pos.y(), hi_y)))

            self.window.move(new_pos)
            event.accept()

    def mouse_release_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            geo = self.window.frameGeometry()
            self.config.set("pos_x", geo.left(), save=False)
            self.config.set("pos_y", geo.top(), save=False)
            self.config.save_debounced()
            event.accept()

    def close_event(self, event):
        """
        关闭窗口 → 最小化到托盘。无托盘场景由 main.py 的 closeEvent
        分支负责调用 quit_app。Qt 的 closeEvent 不使用返回值，语义
        完全靠 event.ignore() 表达。
        """
        event.ignore()
        self.window.hide()

    def save_position(self):
        geo = self.window.frameGeometry()
        self.config.set("pos_x", geo.left(), save=False)
        self.config.set("pos_y", geo.top(), save=False)
        self.config.flush()
        
        
