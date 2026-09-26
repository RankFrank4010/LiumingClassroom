"""统一设置页外观的工具。

复刻 `view/menu/*.ui` 设置页的版式，使以代码构建的页面（值日生 / 远程配置）与
其余基于 .ui 的设置页外观一致：

- 页面根：透明背景 + `SmoothScrollArea`（内容边距 24，块间距 24）
- `TitleLabel` 标题
- 每个分区：`SubtitleLabel` + 若干卡片，卡片间距 3
- 设置行卡片：`CardWidget`，最小高度 70，内边距 16，
  左侧 `StrongBodyLabel`（标题）+ `CaptionLabel`（说明），右侧控件
"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget,
    CaptionLabel,
    SmoothScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

__all__ = [
    'build_scroll_page',
    'add_title',
    'new_section',
    'add_subtitle',
    'setting_card',
    'block_card',
    'panel',
]


def build_scroll_page(page: QWidget) -> Tuple[QVBoxLayout, QWidget]:
    """构建规范设置页容器，返回 (内容布局, 内容控件)。"""
    page.setStyleSheet('background: transparent; border: none')

    root = QVBoxLayout(page)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(18)

    scroll = SmoothScrollArea(page)
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet('background: transparent; border: none;')
    root.addWidget(scroll)

    content = QWidget()
    scroll.setWidget(content)

    layout = QVBoxLayout(content)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(24)
    return layout, content


def add_title(layout: QVBoxLayout, text: str) -> None:
    layout.addWidget(TitleLabel(text))


def new_section(layout: QVBoxLayout) -> QVBoxLayout:
    """新建一个分区（间距 3：分区标题与其卡片紧贴，与 .ui 设置页一致）。"""
    section = QVBoxLayout()
    section.setSpacing(3)
    layout.addLayout(section)
    return section


def add_subtitle(section: QVBoxLayout, text: str) -> None:
    section.addWidget(SubtitleLabel(text))


def setting_card(
    title: str,
    desc: str = '',
    control: Optional[QWidget] = None,
    min_height: int = 70,
    expand_control: bool = False,
) -> CardWidget:
    """一行设置卡片：左标题/说明 + 右控件。"""
    card = CardWidget()
    card.setMinimumHeight(min_height)

    row = QHBoxLayout(card)
    row.setContentsMargins(16, 16, 16, 16)
    row.setSpacing(16)

    text = QVBoxLayout()
    text.setSpacing(0)

    title_label = StrongBodyLabel(title, card)
    title_label.setWordWrap(True)
    text.addWidget(title_label)

    if desc:
        desc_label = CaptionLabel(desc, card)
        desc_label.setWordWrap(True)
        text.addWidget(desc_label)

    row.addLayout(text, 1)
    if control is not None:
        row.addWidget(control, 1 if expand_control else 0)
    return card


def block_card(
    section: QVBoxLayout,
    title: str = '',
    desc: str = '',
    min_height: int = 0,
) -> QVBoxLayout:
    """块状卡片（承载表格、多行文本等），返回可继续添加内容的布局。"""
    card = CardWidget()
    if min_height:
        card.setMinimumHeight(min_height)

    body = QVBoxLayout(card)
    body.setContentsMargins(16, 16, 16, 16)
    body.setSpacing(10)

    if title:
        head = QVBoxLayout()
        head.setSpacing(0)
        title_label = StrongBodyLabel(title, card)
        title_label.setWordWrap(True)
        head.addWidget(title_label)
        if desc:
            desc_label = CaptionLabel(desc, card)
            desc_label.setWordWrap(True)
            head.addWidget(desc_label)
        body.addLayout(head)

    section.addWidget(card)
    return body


def panel(section: QVBoxLayout) -> Tuple[QWidget, QVBoxLayout]:
    """分区内的可显隐面板（透明容器，内部卡片间距同样为 3）。"""
    widget = QWidget()
    inner = QVBoxLayout(widget)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(3)
    section.addWidget(widget)
    return widget, inner
