# coding: utf-8
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QWidget, QApplication
from desktop_calendar.config.manager import ConfigManager, get_logger

logger = get_logger()

class WindowStateManager:
    """窗口状态管理：拖拽、置顶、透明度、位置记忆、边界限制。"""

    def __init__(self, window: QWidget, config: ConfigManager):
        self.window = window
        self.config = config
        self._drag_pos = QPoint()
        self._is_dragging = False

        try:
            opacity = float(config.get("opacity", 0.92))
        except (TypeError, ValueError):
            opacity = 0.92
        # 走 set_opacity 做类型转换与 [0,1] clamp：配置可能被外部工具
        # 写成字符串或百分数，直接 setWindowOpacity 会抛或越界。
        self.set_opacity(opacity)

        if config.get("topmost", False):
            # _setup_window 可能已写入 WindowStaysOnTopHint；再调
            # setWindowFlag 会重建原生句柄，导致 DWM 修复丢失。
            if not (self.window.windowFlags()
                    & Qt.WindowType.WindowStaysOnTopHint):
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

    def ensure_on_screen(self) -> None:
        """确保窗口至少部分在某个屏幕的可用区域内。

        场景：用户把窗口拖到屏幕边缘外（只剩 100px 可见），或拖到副屏
        后拔掉副屏，窗口位置落在"不存在的屏幕"坐标系上。此时 showNormal()
        不会移动窗口，用户看不到也点不到，从托盘恢复也无效。

        用 frameGeometry（含标题栏 / 边框）判断：窗口边缘与任一屏幕的
        availableGeometry 相交即视为可见。完全不相交则移到主屏中心。

        不在此处写 config：位置由 mouse_release_event / save_position
        持久化；这里只是运行期纠正，重启后若不再次拖到屏外则恢复正常。
        """
        frame = self.window.frameGeometry()
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(frame):
                return
        primary = QApplication.primaryScreen()
        if primary is None:
            return
        avail = primary.availableGeometry()
        # 用 frameGeometry 中心对齐屏幕中心，而非 move 到 (0,0)：
        # 后者会让窗口出现在屏幕左上角，遮挡任务栏 / 其他窗口。
        target = avail.center() - frame.rect().center()
        logger.info(
            "窗口完全在屏幕外，重置到主屏中心 (frame=%s, screens=%d)",
            frame.getRect(), len(QApplication.screens()))
        self.window.move(target)

    def save_position(self):
        geo = self.window.frameGeometry()
        self.config.set("pos_x", geo.left(), save=False)
        self.config.set("pos_y", geo.top(), save=False)
        self.config.flush()
        
        
