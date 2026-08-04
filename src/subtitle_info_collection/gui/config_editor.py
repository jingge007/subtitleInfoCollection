from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    DoubleSpinBox,
    HeaderCardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
    FluentIcon as FIF,
)
from qfluentwidgets.common.color import autoFallbackThemeColor
from qfluentwidgets.common.style_sheet import isDarkTheme

from ..config import (
    CONFIG_GROUP_LABELS,
    CONFIG_GROUP_LOCAL,
    CONFIG_GROUP_NETWORK,
    CONFIG_GROUP_SECRETS,
    CONFIG_GROUP_STRATEGY,
    CONFIG_GROUP_SUBHD,
    ENV_FIELD_META,
    AppSettings,
    EnvFieldMeta,
    DEFAULT_PROVIDER_PRIORITY,
    parse_bool,
    parse_csv,
    parse_float,
    parse_int,
    parse_optional_int,
    parse_ratio,
)
from .styles import (
    PRIMARY,
    TEXT,
    TEXT_PLACEHOLDER,
    TEXT_SOFT,
)

PAGE_SPACING = 8

GROUP_TITLES = {
    **CONFIG_GROUP_LABELS,
}


class TogglePasswordLineEdit(PasswordLineEdit):
    """密钥输入框：点击眼睛图标切换明文/掩码，保持显示直到再次点击"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setClearButtonEnabled(True)
        self.setViewPasswordButtonVisible(True)
        self._sync_view_icon()

    # 拦截眼睛按钮：按点击切换，而不是按住才显示
    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.viewButton and self.isEnabled():
            if e.type() == QEvent.Type.MouseButtonRelease and e.button() == Qt.LeftButton:
                self.setPasswordVisible(not self.isPasswordVisible())
                self._sync_view_icon()
                return True
            if e.type() == QEvent.Type.MouseButtonPress:
                return True
        return LineEdit.eventFilter(self, obj, e)

    # 按当前显示状态更新眼睛图标
    def _sync_view_icon(self) -> None:
        self.viewButton.setIcon(FIF.HIDE if self.isPasswordVisible() else FIF.VIEW)


class CopyableKeyLabel(CaptionLabel):
    """可点击复制的 env 配置键标签"""

    clicked = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        # CaptionLabel 使用 singledispatch：子类只能先传 parent，再 setText
        super().__init__(parent)
        self._key = key
        self.setText(key)
        self.setToolTip(f"点击复制配置键：{key}")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"color: {PRIMARY}; text-decoration: underline;")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)


class NoWheelSpinBox(SpinBox):
    """整数微调框：忽略滚轮改值，把滚轮交给外层页面滚动"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 避免鼠标悬停滚轮时自动聚焦并改值
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class NoWheelDoubleSpinBox(DoubleSpinBox):
    """小数微调框：忽略滚轮改值，把滚轮交给外层页面滚动"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class FullWidthIndicatorSegmentedWidget(SegmentedWidget):
    """分段导航：选中指示条拉满当前 Tab 宽度"""

    # 绘制选中背景与与 Tab 同宽的底部指示条
    def paintEvent(self, e) -> None:  # noqa: N802
        QWidget.paintEvent(self, e)

        if not self.currentItem():
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        if isDarkTheme():
            painter.setPen(QColor(255, 255, 255, 14))
            painter.setBrush(QColor(255, 255, 255, 15))
        else:
            painter.setPen(QColor(0, 0, 0, 19))
            painter.setBrush(QColor(255, 255, 255, 179))

        item = self.currentItem()
        slide_x = int(self.slideAni.value())
        rect = item.rect().adjusted(1, 1, -1, -1).translated(slide_x, 0)
        painter.drawRoundedRect(rect, 5, 5)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            autoFallbackThemeColor(self.lightIndicatorColor, self.darkIndicatorColor)
        )
        # 左右各留 4px，指示条与 Tab 视觉同宽
        indicator_width = max(item.width() - 8, 8)
        painter.drawRoundedRect(
            QRectF(slide_x + 4, self.height() - 3.5, indicator_width, 3),
            1.5,
            1.5,
        )


class ConfigEditorWidget(QWidget):
    """配置项编辑器：从 .env 对齐展示，保存时回写键值"""

    save_clicked = Signal()
    reload_clicked = Signal()
    open_env_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widgets: dict[str, Any] = {}
        self._build_ui()

    # 构建分段导航与各组表单
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(PAGE_SPACING)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("配置项")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("以 .env 为权威来源；修改后保存将同步写回本地 .env 文件")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        self.reload_button = PushButton("重新加载", self)
        self.reload_button.setIcon(FIF.SYNC)
        self.reload_button.clicked.connect(self.reload_clicked.emit)
        self.open_env_button = PushButton("打开 .env", self)
        self.open_env_button.setIcon(FIF.FOLDER)
        self.open_env_button.clicked.connect(self.open_env_clicked.emit)
        self.save_button = PrimaryPushButton("保存全部", self)
        self.save_button.setIcon(FIF.SAVE)
        self.save_button.clicked.connect(self.save_clicked.emit)
        header.addWidget(self.reload_button)
        header.addWidget(self.open_env_button)
        header.addWidget(self.save_button)
        root.addLayout(header)

        self.segment = FullWidthIndicatorSegmentedWidget(self)
        self.stack = QStackedWidget(self)
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._group_pages: dict[str, QWidget] = {}
        for group in [
            CONFIG_GROUP_SECRETS,
            CONFIG_GROUP_STRATEGY,
            CONFIG_GROUP_SUBHD,
            CONFIG_GROUP_NETWORK,
            CONFIG_GROUP_LOCAL,
        ]:
            page = self._build_group_page(group)
            self._group_pages[group] = page
            self.stack.addWidget(page)
            self.segment.addItem(routeKey=group, text=GROUP_TITLES[group])

        self.segment.setCurrentItem(CONFIG_GROUP_SECRETS)
        self.segment.currentItemChanged.connect(self._on_group_changed)
        root.addWidget(self.segment)
        root.addWidget(self.stack, 1)

    # 按分组生成可编辑表单
    def _build_group_page(self, group: str) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(PAGE_SPACING)
        card = self._card(GROUP_TITLES[group])
        form = QVBoxLayout()
        form.setSpacing(10)
        for meta in ENV_FIELD_META:
            if meta.group != group:
                continue
            form.addLayout(self._build_field_row(meta))
        card.viewLayout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _card(self, title: str) -> HeaderCardWidget:
        card = HeaderCardWidget(self)
        card.setTitle(title)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.headerLayout.setContentsMargins(14, 8, 14, 0)
        card.viewLayout.setContentsMargins(14, 6, 14, 10)
        card.viewLayout.setSpacing(PAGE_SPACING)
        return card

    # 构建单个配置字段行
    def _build_field_row(self, meta: EnvFieldMeta) -> QVBoxLayout:
        block = QVBoxLayout()
        block.setSpacing(4)
        label_row = QHBoxLayout()
        label_row.setSpacing(6)
        label = StrongBodyLabel(meta.label)
        label.setStyleSheet(f"font-size: 13px; color: {TEXT};")
        key_caption = CopyableKeyLabel(meta.key, self)
        key_caption.clicked.connect(self._copy_env_key)
        copy_button = TransparentToolButton(FIF.COPY, self)
        copy_button.setFixedSize(28, 28)
        copy_button.setToolTip(f"复制配置键：{meta.key}")
        copy_button.clicked.connect(lambda _=False, key=meta.key: self._copy_env_key(key))
        label_row.addWidget(label)
        label_row.addWidget(key_caption)
        label_row.addWidget(copy_button)
        label_row.addStretch(1)
        block.addLayout(label_row)

        desc = CaptionLabel(meta.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_SOFT};")
        block.addWidget(desc)

        control_row = QHBoxLayout()
        control_row.setSpacing(8)
        widget = self._create_widget(meta)
        self._widgets[meta.key] = widget
        control_row.addWidget(widget, 1)

        if meta.widget == "path":
            browse = PushButton("选择", self)
            browse.setIcon(FIF.FOLDER)
            browse.clicked.connect(lambda _=False, key=meta.key: self._browse_path(key))
            control_row.addWidget(browse)
        block.addLayout(control_row)
        return block

    # 复制 env 配置键名到剪贴板
    def _copy_env_key(self, key: str) -> None:
        QGuiApplication.clipboard().setText(key)
        InfoBar.success(
            "已复制",
            key,
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=1800,
        )

    # 按元数据类型创建控件
    def _create_widget(self, meta: EnvFieldMeta) -> QWidget:
        if meta.widget == "secret":
            return TogglePasswordLineEdit(self)
        if meta.widget == "bool":
            switch = SwitchButton(self)
            switch.setOnText("开")
            switch.setOffText("关")
            return switch
        if meta.widget == "int":
            spin = NoWheelSpinBox(self)
            spin.setRange(0, 1_000_000)
            spin.setMinimumWidth(160)
            return spin
        if meta.widget in {"float", "optional_int"}:
            if meta.widget == "float":
                spin = NoWheelDoubleSpinBox(self)
                spin.setDecimals(2)
                spin.setRange(0.0, 1.0)
                spin.setSingleStep(0.05)
                spin.setMinimumWidth(160)
                return spin
            edit = LineEdit(self)
            edit.setPlaceholderText("留空=自动")
            edit.setClearButtonEnabled(True)
            return edit
        edit = LineEdit(self)
        edit.setClearButtonEnabled(True)
        return edit

    # 选择目录并填入路径字段
    def _browse_path(self, key: str) -> None:
        widget = self._widgets.get(key)
        if not isinstance(widget, LineEdit):
            return
        start = widget.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择目录", start)
        if directory:
            widget.setText(directory)

    def _on_group_changed(self, route_key: str) -> None:
        page = self._group_pages.get(route_key)
        if page is not None:
            self.stack.setCurrentWidget(page)

    # 用 AppSettings（来自 .env）填充全部表单
    def load_from_settings(self, settings: AppSettings) -> None:
        values = settings.to_env_values()
        for meta in ENV_FIELD_META:
            widget = self._widgets.get(meta.key)
            if widget is None:
                continue
            raw = values.get(meta.key, "")
            if meta.widget == "bool":
                widget.setChecked(parse_bool(raw, False))
            elif meta.widget == "int":
                if meta.key == "SUBTITLE_REQUEST_INTERVAL_MS":
                    widget.setRange(12_000, 1_000_000)
                    widget.setValue(max(12_000, parse_int(raw, 13_000)))
                elif meta.key == "SUBTITLE_MOVIE_CONCURRENCY":
                    widget.setRange(1, 4)
                    widget.setValue(max(1, min(4, parse_int(raw, 2))))
                elif meta.key in {"SUBHD_SEARCH_TIMEOUT", "PROVIDER_SEARCH_TIMEOUT"}:
                    widget.setRange(30, 3600)
                    widget.setValue(max(30, parse_int(raw, 90)))
                else:
                    widget.setValue(parse_int(raw, 0))
            elif meta.widget == "float":
                widget.setValue(parse_float(raw, 0.0))
            else:
                widget.setText(raw)

    # 收集表单值为可写回 .env 的字符串字典
    def collect_env_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for meta in ENV_FIELD_META:
            widget = self._widgets[meta.key]
            if meta.widget == "bool":
                values[meta.key] = "true" if widget.isChecked() else "false"
            elif meta.widget == "int":
                values[meta.key] = str(int(widget.value()))
            elif meta.widget == "float":
                values[meta.key] = f"{float(widget.value()):.2f}"
            elif meta.widget == "optional_int":
                text = widget.text().strip()
                if text:
                    parsed = parse_optional_int(text)
                    if parsed is None or parsed < 1:
                        raise ValueError(f"{meta.label} 须为正整数，或留空表示自动。")
                    values[meta.key] = str(parsed)
                else:
                    values[meta.key] = ""
            else:
                values[meta.key] = widget.text().strip()

        # 校验字幕源优先级
        priority = parse_csv(values.get("SUBTITLE_PROVIDER_PRIORITY"), [])
        if not priority:
            values["SUBTITLE_PROVIDER_PRIORITY"] = ",".join(DEFAULT_PROVIDER_PRIORITY)
        else:
            unknown = [item for item in priority if item not in DEFAULT_PROVIDER_PRIORITY]
            if unknown:
                raise ValueError(f"未知字幕源：{', '.join(unknown)}")
            values["SUBTITLE_PROVIDER_PRIORITY"] = ",".join(priority)

        disabled = parse_csv(values.get("SUBTITLE_PROVIDER_DISABLED"), [])
        values["SUBTITLE_PROVIDER_DISABLED"] = ",".join(disabled)

        ratio = parse_ratio(values.get("SUBTITLE_MIN_BILINGUAL_RATIO"), -1.0)
        if ratio < 0:
            raise ValueError("双语最低占比须为 0.0～1.0 的数字。")
        values["SUBTITLE_MIN_BILINGUAL_RATIO"] = f"{ratio:.2f}"

        confidence = parse_float(
            values.get("SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE"), -1.0
        )
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("OCR 自动提交置信度须为 0.0～1.0。")
        values["SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE"] = f"{confidence:.2f}"

        interval = parse_int(values.get("SUBTITLE_REQUEST_INTERVAL_MS"), 0)
        values["SUBTITLE_REQUEST_INTERVAL_MS"] = str(max(12_000, interval))

        concurrency = parse_int(values.get("SUBTITLE_MOVIE_CONCURRENCY"), 2)
        values["SUBTITLE_MOVIE_CONCURRENCY"] = str(max(1, min(4, concurrency)))

        data_dir = values.get("SUBTITLE_COLLECTION_DATA_DIR", "").strip()
        if data_dir:
            values["SUBTITLE_COLLECTION_DATA_DIR"] = str(Path(data_dir).expanduser())
        return values
