#!/usr/bin/env python3
"""从品牌 SVG 生成应用/品牌图标（ICO / ICNS / PNG）。

- 输入：项目根目录的 ``liumingclassroom-icon-light.svg``
- 输出：img/ 与 img/logo/ 下的应用图标（窗口/任务栏/托盘/安装包/关于页）
- 仅依赖 PyQt5（QtSvg 渲染），无需 Pillow / ImageMagick。

用法（在 LiumingClassroom 目录，使用带 PyQt5 的解释器）：

    python tools/make_app_icons.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PyQt5.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PyQt5.QtGui import QImage, QPainter, QPainterPath
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / 'liumingclassroom-icon-light.svg'

# SVG 中圆角半径 112.6 / 512；渲染时强制裁剪，避免不同 SVG 渲染器对
# clip-path 支持差异导致圆角丢失。
CORNER_RATIO = 112.6 / 512.0


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    """把 SVG 渲染为 size×size 的透明 PNG 字节（带圆角裁剪）。"""
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    radius = CORNER_RATIO * size
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(path)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


def write_ico(path: Path, entries: list[tuple[int, bytes]]) -> None:
    """写多尺寸 ICO（PNG 压缩条目，Windows Vista+ 支持）。"""
    entries = sorted(entries, key=lambda item: item[0])
    count = len(entries)
    header = struct.pack('<HHH', 0, 1, count)
    offset = 6 + 16 * count

    directory = b''
    payload = b''
    for size, data in entries:
        dim = 0 if size >= 256 else size
        directory += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data

    path.write_bytes(header + directory + payload)


def write_icns(path: Path, entries: list[tuple[bytes, bytes]]) -> None:
    """写 ICNS（各尺寸以 PNG 数据内嵌）。"""
    body = b''
    for kind, data in entries:
        body += kind + struct.pack('>I', 8 + len(data)) + data
    path.write_bytes(b'icns' + struct.pack('>I', 8 + len(body)) + body)


def main() -> int:
    app = QApplication(sys.argv[:1])  # noqa: F841 - Qt 需要一个实例

    if not SVG.exists():
        print(f'缺少源文件: {SVG}')
        return 1

    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    if not renderer.isValid():
        print('SVG 无效，无法渲染')
        return 1

    cache: dict[int, bytes] = {}

    def png(size: int) -> bytes:
        if size not in cache:
            cache[size] = render_png(renderer, size)
        return cache[size]

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]

    def ico(relative: str) -> None:
        write_ico(ROOT / relative, [(size, png(size)) for size in ico_sizes])
        print('ico ', relative)

    def png_file(relative: str, size: int) -> None:
        (ROOT / relative).write_bytes(png(size))
        print('png ', relative, f'({size}px)')

    # 主应用图标
    png_file('img/favicon.png', 256)
    ico('img/favicon.ico')
    write_icns(
        ROOT / 'img/favicon.icns',
        [
            (b'icp4', png(16)),
            (b'icp5', png(32)),
            (b'icp6', png(64)),
            (b'ic07', png(128)),
            (b'ic08', png(256)),
            (b'ic09', png(512)),
        ],
    )
    print('icns  img/favicon.icns')

    # 各窗口 / 托盘 / 关于页使用的品牌图标
    png_file('img/logo/favicon.png', 256)
    ico('img/logo/favicon.ico')
    ico('img/logo/favicon-settings.ico')
    ico('img/logo/favicon-exmenu.ico')
    ico('img/logo/favicon-error.ico')
    png_file('img/logo/favicon-update.png', 128)
    png_file('img/pp_favicon.png', 256)
    png_file('img/Logo.png', 512)

    print('完成')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
