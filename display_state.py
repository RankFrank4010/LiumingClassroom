"""显示状态全局标志（无第三方依赖，供各模块安全导入避免循环引用）。

- 全屏（如用户放映 PPT）时：小组件全部隐藏、事件提示（toast/值日弹窗）屏蔽。
- 状态由 main.py 的周期任务根据前台窗口检测结果刷新。
"""

from __future__ import annotations

_fullscreen = False  # 前台存在全屏应用（PPT 放映等）


def set_fullscreen(value: bool) -> None:
    global _fullscreen
    _fullscreen = bool(value)


def is_fullscreen() -> bool:
    return _fullscreen
