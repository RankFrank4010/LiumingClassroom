"""启动辅助依赖检测（Windows）。

支持 Windows 7 SP1 / 8 / 8.1 / 10 / 11，x86 与 x64 全平台。
可自动检测并（可选）静默安装运行本软件所需的运行库。

用法：
    python dep_check.py            # 仅检测并打印报告
    python dep_check.py --json     # 以 JSON 输出报告
    python dep_check.py --auto     # 检测并自动安装缺失项（可能弹 UAC）
    python dep_check.py --auto --quiet

也可被 main.py 导入：``check_runtime()`` 返回报告，``install_missing(report)`` 执行安装。
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
import urllib.request

# --------------------------------------------------------------------------- #
# 基础信息
# --------------------------------------------------------------------------- #
def architecture() -> str:
    """返回 'x64' 或 'x86'。"""
    return 'x64' if struct.calcsize('P') * 8 == 64 else 'x86'


def windows_info() -> dict:
    """返回 Windows 版本/位数信息（覆盖 Win7 起各版本）。"""
    try:
        v = sys.getwindowsversion()
        major, minor, build = v.major, v.minor, v.build
    except Exception:
        major, minor, build = 0, 0, 0
    if (major, minor) == (6, 1):
        name = 'Windows 7'
    elif (major, minor) == (6, 2):
        name = 'Windows 8'
    elif (major, minor) == (6, 3):
        name = 'Windows 8.1'
    elif (major, minor) == (10, 0):
        name = 'Windows 11' if build >= 22000 else 'Windows 10'
    else:
        name = f'Windows {major}.{minor}'
    return {
        'name': name,
        'major': major,
        'minor': minor,
        'build': build,
        'arch': architecture(),
        'is_win7': (major, minor) == (6, 1),
        'is_windows': os.name == 'nt',
    }


def app_dir() -> str:
    """程序所在目录（打包后为 exe 目录）。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _system_root() -> str:
    return os.environ.get('SystemRoot', r'C:\Windows')


def _search_dirs() -> list:
    root = _system_root()
    dirs = [app_dir(), os.path.join(app_dir(), 'PyQt5', 'Qt5', 'bin'), os.path.join(root, 'System32')]
    if architecture() == 'x64':
        dirs.append(os.path.join(root, 'SysWOW64'))
    return [d for d in dirs if os.path.isdir(d)]


def find_dll(name: str):
    if not name.lower().endswith('.dll'):
        name += '.dll'
    for d in _search_dirs():
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def can_load(name: str) -> bool:
    if os.name != 'nt':
        return True
    try:
        ctypes.WinDLL(name)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# 依赖检测
# --------------------------------------------------------------------------- #
def _vcruntime_ok() -> bool:
    return can_load('msvcp140') or can_load('vcruntime140') or bool(find_dll('msvcp140'))


def _ucrt_ok() -> bool:
    return can_load('ucrtbase') or bool(find_dll('ucrtbase'))


def _dx_ok() -> bool:
    return can_load('d3dcompiler_47') or bool(find_dll('d3dcompiler_47'))


def _sp1_ok() -> bool:
    """Windows 7 必须是 SP1（build >= 7601）。"""
    info = windows_info()
    return True if not info['is_win7'] else info['build'] >= 7601


def _kb2533623_ok() -> bool:
    """KB2533623 提供 AddDllDirectory/SetDefaultDllDirectories（Python 3.8 与 Qt 需要）。"""
    if os.name != 'nt':
        return True
    try:
        getattr(ctypes.windll.kernel32, 'AddDllDirectory')
        return True
    except Exception:
        return False


def check_runtime() -> dict:
    """检测运行所需依赖，返回报告 dict。"""
    info = windows_info()
    components = [
        {
            'id': 'sp1',
            'name': 'Windows 7 Service Pack 1',
            'ok': _sp1_ok(),
            'auto': False,
        },
        {
            'id': 'kb2533623',
            'name': 'Windows 7 更新 KB2533623（DLL 目录支持）',
            'ok': _kb2533623_ok(),
            'auto': False,
        },
        {
            'id': 'vcredist',
            'name': 'Microsoft Visual C++ 2015-2022 运行库',
            'ok': _vcruntime_ok(),
            'auto': True,
        },
        {
            'id': 'ucrt',
            'name': 'Universal C Runtime (UCRT)',
            'ok': _ucrt_ok(),
            'auto': bool(info['is_win7']),
        },
        {
            'id': 'dx',
            'name': 'DirectX 运行时 (d3dcompiler_47)',
            'ok': _dx_ok(),
            'auto': True,
        },
    ]
    return {
        'windows': info,
        'components': components,
        'all_ok': all(c['ok'] for c in components),
    }


# --------------------------------------------------------------------------- #
# 安装
# --------------------------------------------------------------------------- #
_VC_URLS = {
    'x64': 'https://aka.ms/vs/17/release/vc_redist.x64.exe',
    'x86': 'https://aka.ms/vs/17/release/vc_redist.x86.exe',
}
# Windows 7 使用 VS2019 (14.29) 版本，对 SHA-2 要求更宽松
_VC_WIN7_URLS = {
    'x64': 'https://aka.ms/vs/16/release/vc_redist.x64.exe',
    'x86': 'https://aka.ms/vs/16/release/vc_redist.x86.exe',
}
_UCRT_WIN7 = {
    'x64': ('https://download.microsoft.com/download/9/3/F/'
            '93FCF1E7-E6A4-478B-96E7-D4B285925B00/Windows6.1-KB2999226-x64.msu'),
    'x86': ('https://download.microsoft.com/download/9/3/F/'
            '93FCF1E7-E6A4-478B-96E7-D4B285925B00/Windows6.1-KB2999226-x86.msu'),
}
_DX_URL = ('https://download.microsoft.com/download/1/7/1/'
           '1718CCC4-6315-4D8E-9543-8E28A4E18C4C/dxwebsetup.exe')


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _download(url: str, quiet: bool = False) -> str:
    name = os.path.basename(url.split('?')[0]) or 'dep.exe'
    dest = os.path.join(tempfile.gettempdir(), name)
    if not quiet:
        print(f'  下载 {url}')
    req = urllib.request.Request(url, headers={'User-Agent': 'LiumingClassroom-dep-check'})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, 'wb') as f:  # noqa: S310
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def _run(path: str, params: list, quiet: bool = False) -> int:
    """以管理员权限运行安装器（需要时弹 UAC）。返回退出码（-1 表示无法获取）。"""
    if _is_admin():
        proc = subprocess.run([path] + params, check=False)  # noqa: S603
        return proc.returncode
    # 非管理员：通过 UAC 提权运行
    args = ' '.join(f'"{a}"' if ' ' in a else a for a in params)
    rc = ctypes.windll.shell32.ShellExecuteW(None, 'runas', path, args, None, 1)
    return 0 if rc > 32 else -1


def install_vcredist(quiet: bool = False) -> bool:
    info = windows_info()
    arch = info['arch']
    if info['is_win7']:
        url = _VC_WIN7_URLS.get(arch, _VC_URLS[arch])
    else:
        url = _VC_URLS[arch]
    if not quiet:
        print(f'安装 VC++ 运行库 ({arch}) ...')
    local = os.path.join(app_dir(), f'vc_redist.{arch}.exe')
    path = local if os.path.exists(local) else _download(url, quiet)
    rc = _run(path, ['/install', '/quiet', '/norestart'], quiet)
    return rc in (0, 3010, 1638) or _vcruntime_ok()


def install_ucrt(quiet: bool = False) -> bool:
    if not windows_info()['is_win7']:
        return True
    if not quiet:
        print('安装 Windows 7 UCRT (KB2999226) ...')
    path = _download(_UCRT_WIN7[architecture()], quiet)
    rc = _run('wusa.exe', [path, '/quiet', '/norestart'], quiet)
    return rc in (0, 3010) or _ucrt_ok()


def install_directx(quiet: bool = False) -> bool:
    if not quiet:
        print('安装 DirectX 运行时 ...')
    path = _download(_DX_URL, quiet)
    rc = _run(path, ['/Q'], quiet)
    return rc in (0, 3010) or _dx_ok()


_INSTALLERS = {
    'vcredist': install_vcredist,
    'ucrt': install_ucrt,
    'dx': install_directx,
}


def install_missing(report: dict, quiet: bool = False) -> dict:
    """安装报告中缺失且可自动安装的依赖，返回更新后的报告。"""
    for comp in report['components']:
        if comp['ok'] or not comp.get('auto'):
            continue
        installer = _INSTALLERS.get(comp['id'])
        if installer is None:
            continue
        try:
            installer(quiet=quiet)
        except Exception as e:  # noqa: BLE001 - 报告安装失败但不中断
            if not quiet:
                print(f'  {comp["id"]} 安装失败：{e}')
    return check_runtime()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_report(report: dict) -> None:
    w = report['windows']
    print('=' * 60)
    print(f'系统：{w["name"]}（{w["major"]}.{w["minor"]}.{w["build"]} {w["arch"]}）')
    print('-' * 60)
    for c in report['components']:
        print(f'  [{"OK" if c["ok"] else "缺失"}] {c["name"]}')
    print('-' * 60)
    print('全部满足' if report['all_ok'] else '存在缺失项')
    print('=' * 60)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in argv
    auto = '--auto' in argv
    quiet = '--quiet' in argv
    if not windows_info()['is_windows']:
        if as_json:
            print(json.dumps({'windows': windows_info(), 'components': [], 'all_ok': True}))
        return 0
    report = check_runtime()
    if not quiet and not as_json:
        _print_report(report)
    if auto and not report['all_ok']:
        report = install_missing(report, quiet=quiet)
        if not quiet and not as_json:
            print('\n安装后重新检测：')
            _print_report(report)
    if as_json:
        print(json.dumps(report, ensure_ascii=False))
    return 0 if report['all_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
