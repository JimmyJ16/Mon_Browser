import sys
import os

os.environ["QT_DISABLE_WEBENGINE_GPU_WIDGET_COMPOSITION"] = "1"
os.environ["QT_WEBENGINE_DISABLE_GPU_THREAD"] = "0"
os.environ["QT_MAC_WANTS_LAYER"] = "1"

from PySide6.QtCore import QUrl, Qt, QSize, QTimer, QObject, QEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QWidget, QLineEdit, QPushButton, QSplitter, QTabBar
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor

CLOSE_BUTTON_RIGHT_MARGIN = 10
TAB_RIGHT_PADDING = 45


class CircularCloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setFixedSize(24, 24)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.underMouse():
            painter.setBrush(QColor("#E81123"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
            cross_color = QColor("white")
        else:
            cross_color = QColor("#FF8C00")

        pen = QPen(cross_color)
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        padding = 8
        painter.drawLine(padding, padding, self.width() - padding, self.height() - padding)
        painter.drawLine(padding, self.height() - padding, self.width() - padding, padding)
        painter.end()


class PanelFocusFilter(QObject):
    def __init__(self, browser, view, parent=None):
        super().__init__(parent)
        self.browser = browser
        self.view = view

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self.browser.focus_panel(self.view)
        return False


class CustomTabBar(QTabBar):
    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser

    def mousePressEvent(self, event):
        index = self.tabAt(event.pos())
        if index != -1 and self.browser.is_selecting_split_target:
            self.browser.handle_split_selection(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reposition_close_buttons()

    def tabLayoutChange(self):
        super().tabLayoutChange()
        self.reposition_close_buttons()

    def reposition_close_buttons(self):
        for index in range(self.count()):
            btn = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if btn is None:
                continue
            tab_rect = self.tabRect(index)
            x = tab_rect.right() - btn.width() - CLOSE_BUTTON_RIGHT_MARGIN
            y = tab_rect.top() + (tab_rect.height() - btn.height()) // 2
            btn.move(x, y)


class MonBrowser(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Mon")
        self.resize(1200, 800)

        self.setStyleSheet("""
            QMainWindow { background-color: #8C8C8C; }
            QWidget#centralWidget { background-color: #8C8C8C; }
        """)

        self.tabs_data = []
        self.active_panel = None

        self.is_selecting_split_target = False
        self.split_source_idx = None

        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(100)
        self.animation_timer.timeout.connect(self.update_loading_animations)
        self.animation_timer.start()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        tab_row_layout = QHBoxLayout()

        self.tab_bar = CustomTabBar(self, self)
        self.tab_bar.setTabsClosable(False)
        self.tab_bar.setMovable(True)
        self.tab_bar.setIconSize(QSize(16, 16))

        self.tab_bar.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: white;
                color: #333333;
                font-family: Arial;
                font-size: 14px;
                padding: 14px {TAB_RIGHT_PADDING}px 14px 20px;
                margin-right: 5px;
                min-width: 180px;
                max-width: 280px;
                border: none;
            }}
            QTabBar::tab:selected {{
                background-color: #FFFFFF;
                font-weight: bold;
            }}
            QTabBar::tab:!selected {{
                background-color: #D6D6D6;
            }}
        """)

        self.tab_bar.currentChanged.connect(self.switch_tab_view)

        add_tab_btn = QPushButton("+")
        add_tab_btn.setFixedSize(38, 38)
        add_tab_btn.setStyleSheet("""
            QPushButton {
                background-color: white; color: #333333; font-weight: bold; font-size: 20px; border: none;
            }
            QPushButton:hover { background-color: #E6E6E6; }
        """)
        add_tab_btn.clicked.connect(lambda: self.add_new_tab("https://google.com"))

        tab_row_layout.addWidget(self.tab_bar)
        add_tab_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tab_row_layout.addWidget(add_tab_btn)
        tab_row_layout.addStretch()

        navbar = QHBoxLayout()
        navbar.setSpacing(8)

        button_style = """
            QPushButton {
                background-color: transparent; border: none; color: #FF8C00;
                font-size: 24px; font-weight: bold; width: 40px; height: 40px;
            }
            QPushButton:hover { background-color: #9C9C9C; }
            QPushButton:disabled { color: #B0B0B0; }
        """

        self.split_btn = QPushButton("||")
        self.split_btn.setStyleSheet(button_style)
        self.split_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.split_btn.clicked.connect(self.trigger_split_selection_mode)

        self.back_btn = QPushButton("◀")
        self.back_btn.setStyleSheet(button_style)
        self.back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(lambda: self.active_panel.back() if self.active_panel else None)

        self.forward_btn = QPushButton("▶")
        self.forward_btn.setStyleSheet(button_style)
        self.forward_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.forward_btn.setEnabled(False)
        self.forward_btn.clicked.connect(lambda: self.active_panel.forward() if self.active_panel else None)

        reload_btn = QPushButton("⟳")
        reload_btn.setStyleSheet(button_style)
        reload_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        reload_btn.clicked.connect(lambda: self.active_panel.reload() if self.active_panel else None)

        self.url_bar = QLineEdit()
        self.url_bar.setFixedHeight(40)
        self.url_bar.setStyleSheet("""
            QLineEdit {
                background-color: white; border: none; font-family: Arial;
                font-size: 16px; padding-left: 10px; color: #333333;
            }
        """)
        self.url_bar.returnPressed.connect(self.navigate_address)

        navbar.addWidget(self.split_btn)
        navbar.addWidget(self.back_btn)
        navbar.addWidget(self.forward_btn)
        navbar.addWidget(reload_btn)
        navbar.addWidget(self.url_bar)

        self.container_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.container_splitter.setOpaqueResize(True)
        self.container_splitter.setStyleSheet("QSplitter::handle { background-color: #8C8C8C; width: 6px; }")

        main_layout.addLayout(tab_row_layout)
        main_layout.addLayout(navbar)
        main_layout.addWidget(self.container_splitter)

        container = QWidget()
        container.setObjectName("centralWidget")
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.add_new_tab("https://google.com")

    def update_split_button_state(self):
        if len(self.tabs_data) >= 2:
            self.split_btn.setEnabled(True)
        else:
            self.split_btn.setEnabled(False)

    def attach_mouse_filters(self, view):
        focus_filter = PanelFocusFilter(self, view, parent=view)
        view.installEventFilter(focus_filter)

        if view.focusProxy():
            view.focusProxy().installEventFilter(focus_filter)

        for child in view.children():
            child.installEventFilter(focus_filter)

    def add_new_tab(self, url_str):
        left_view = QWebEngineView()
        right_view = QWebEngineView()
        left_view.setObjectName("left_view")
        right_view.setObjectName("right_view")

        self.container_splitter.addWidget(left_view)
        self.container_splitter.addWidget(right_view)

        self.tab_bar.blockSignals(True)
        tab_index = self.tab_bar.addTab("")
        self.tab_bar.blockSignals(False)

        tab_meta = {
            "left": left_view,
            "right": right_view,
            "is_split": False,
            "right_initialized": False,
            "loading_angle": 0,
            "left_loading": False,
            "right_loading": False,
            "current_title": "",
            "fav_icon": QIcon()
        }
        self.tabs_data.append(tab_meta)

        self.attach_mouse_filters(left_view)
        self.attach_mouse_filters(right_view)

        left_view.urlChanged.connect(lambda qurl, lv=left_view: self.sync_ui_address(qurl, lv))
        right_view.urlChanged.connect(lambda qurl, rv=right_view: self.sync_ui_address(qurl, rv))

        left_view.titleChanged.connect(lambda title, lv=left_view: self.update_tab_title_by_view(title, lv, "left"))
        right_view.titleChanged.connect(lambda title, rv=right_view: self.update_tab_title_by_view(title, rv, "right"))

        left_view.loadStarted.connect(lambda lv=left_view: self.handle_load_start_by_view(lv, "left"))
        right_view.loadStarted.connect(lambda rv=right_view: self.handle_load_start_by_view(rv, "right"))

        left_view.loadFinished.connect(lambda ok, lv=left_view: self.handle_load_finish_by_view(lv, "left"))
        right_view.loadFinished.connect(lambda ok, rv=right_view: self.handle_load_finish_by_view(rv, "right"))

        left_view.iconChanged.connect(lambda icon, lv=left_view: self.update_tab_favicon_by_view(icon, lv, "left"))
        right_view.iconChanged.connect(lambda icon, rv=right_view: self.update_tab_favicon_by_view(icon, rv, "right"))

        close_btn = CircularCloseButton()
        close_btn.clicked.connect(lambda checked=False, target_view=left_view: self.close_tab_by_widget(target_view))

        self.tab_bar.setTabButton(tab_index, QTabBar.ButtonPosition.RightSide, close_btn)
        self.tab_bar.reposition_close_buttons()

        self.tab_bar.setCurrentIndex(tab_index)
        self.switch_tab_view(tab_index)

        if not url_str.startswith("http://") and not url_str.startswith("https://") and not url_str.startswith("about:"):
            url_str = "https://" + url_str
        left_view.setUrl(QUrl(url_str))

        self.update_split_button_state()

    def generate_loading_frame(self, angle):
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#FF8C00"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawArc(2, 2, 12, 12, angle * 16, 270 * 16)
        painter.end()
        return QIcon(pixmap)

    def trigger_split_selection_mode(self):
        idx = self.tab_bar.currentIndex()
        if idx == -1 or idx >= len(self.tabs_data):
            return

        tab = self.tabs_data[idx]

        if tab["is_split"]:
            tab["is_split"] = False
            tab["right"].hide()
            self.active_panel = tab["left"]
            self.switch_tab_view(idx)
        else:
            self.is_selecting_split_target = True
            self.split_source_idx = idx
            self.split_btn.setStyleSheet("""
                QPushButton { background-color: #9C9C9C; border: none; color: #FFFFFF;
                font-size: 24px; font-weight: bold; width: 40px; height: 40px; }
            """)

    def handle_split_selection(self, index):
        self.is_selecting_split_target = False
        self.split_btn.setStyleSheet("""
            QPushButton { background-color: transparent; border: none; color: #FF8C00;
            font-size: 24px; font-weight: bold; width: 40px; height: 40px; }
            QPushButton:hover { background-color: #9C9C9C; }
            QPushButton:disabled { color: #B0B0B0; }
        """)

        if index == self.split_source_idx:
            return

        source_tab = self.tabs_data[self.split_source_idx]
        target_tab = self.tabs_data[index]

        target_url = target_tab["left"].url()
        source_tab["is_split"] = True
        source_tab["right"].setUrl(target_url)

        self.close_tab_by_index(index)

        if index < self.split_source_idx:
            self.split_source_idx -= 1

        self.tab_bar.setCurrentIndex(self.split_source_idx)
        self.switch_tab_view(self.split_source_idx)

    def focus_panel(self, view):
        if self.active_panel == view:
            return

        self.active_panel = view
        self.url_bar.setText(view.url().toString())
        self.update_nav_buttons()

    def navigate_address(self):
        if not self.active_panel:
            return
        text = self.url_bar.text().strip()
        if not text:
            return
        if not text.startswith("http://") and not text.startswith("https://") and not text.startswith("about:"):
            text = "https://" + text
        self.active_panel.setUrl(QUrl(text))

    def sync_ui_address(self, qurl, view):
        if view == self.active_panel:
            self.url_bar.setText(qurl.toString())
            self.update_nav_buttons()

    def update_nav_buttons(self):
        if self.active_panel is None:
            self.back_btn.setEnabled(False)
            self.forward_btn.setEnabled(False)
            return
        history = self.active_panel.history()
        self.back_btn.setEnabled(history.canGoBack())
        self.forward_btn.setEnabled(history.canGoForward())

    def update_tab_title_by_view(self, title, view, position):
        for index, tab in enumerate(self.tabs_data):
            if tab[position] == view:
                if position == "left" or (position == "right" and tab["is_split"] and self.active_panel == tab["right"]):
                    tab["current_title"] = title if title.strip() else ""
                    self.tab_bar.setTabText(
                        index,
                        tab["current_title"][:15] + "..." if len(tab["current_title"]) > 15 else tab["current_title"]
                    )

    def handle_load_start_by_view(self, view, position):
        for tab in self.tabs_data:
            if tab[position] == view:
                tab[f"{position}_loading"] = True

    def handle_load_finish_by_view(self, view, position):
        for index, tab in enumerate(self.tabs_data):
            if tab[position] == view:
                tab[f"{position}_loading"] = False
                if not tab["left_loading"] and not tab["right_loading"]:
                    self.tab_bar.setTabIcon(index, tab["fav_icon"])

        self.attach_mouse_filters(view)

        if view == self.active_panel:
            self.update_nav_buttons()

    def update_tab_favicon_by_view(self, icon, view, position):
        for index, tab in enumerate(self.tabs_data):
            if tab[position] == view:
                tab["fav_icon"] = icon
                if not tab[f"{position}_loading"]:
                    self.tab_bar.setTabIcon(index, icon)

    def switch_tab_view(self, index):
        if not (0 <= index < len(self.tabs_data)):
            return

        for item in self.tabs_data:
            try:
                item["left"].hide()
                item["right"].hide()
            except:
                pass

        tab = self.tabs_data[index]
        tab["left"].show()

        if tab["is_split"]:
            tab["right"].show()
            self.container_splitter.setSizes([self.width() // 2, self.width() // 2])

        if tab["is_split"] and self.active_panel == tab["right"]:
            self.active_panel = tab["right"]
        else:
            self.active_panel = tab["left"]

        self.url_bar.setText(self.active_panel.url().toString())
        self.tab_bar.setTabText(
            index,
            tab["current_title"][:15] + "..." if len(tab["current_title"]) > 15 else tab["current_title"]
        )
        self.update_nav_buttons()

    def close_tab_by_widget(self, view):
        for index, tab in enumerate(self.tabs_data):
            if tab["left"] == view:
                self.close_tab_by_index(index)
                break

    def close_tab_by_index(self, idx):
        if 0 <= idx < len(self.tabs_data):
            tab = self.tabs_data.pop(idx)
            tab["left"].deleteLater()
            tab["right"].deleteLater()

            self.tab_bar.blockSignals(True)
            self.tab_bar.removeTab(idx)
            self.tab_bar.blockSignals(False)

            if not self.tabs_data:
                QApplication.quit()
                return

            new_index = self.tab_bar.currentIndex()
            if new_index != -1:
                self.switch_tab_view(new_index)

        self.update_split_button_state()

    def update_loading_animations(self):
        for index, tab in enumerate(self.tabs_data):
            if tab["left_loading"] or tab["right_loading"]:
                tab["loading_angle"] = (tab["loading_angle"] + 15) % 360
                self.tab_bar.setTabIcon(index, self.generate_loading_frame(tab["loading_angle"]))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    browser = MonBrowser()
    browser.show()
    app.processEvents()
    sys.exit(app.exec())
