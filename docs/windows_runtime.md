# Windows 运行环境与启动辅助检测

本软件（打包版）已内置 Python、Qt、PyQt、pywin32 等全部依赖，通常解压即用。
但 Windows 本身仍可能需要以下**系统级运行库**，因此提供启动辅助检测：

| 组件 | 说明 | 何时缺失 |
| --- | --- | --- |
| Microsoft Visual C++ 2015-2022 运行库 | `msvcp140.dll` / `vcruntime140.dll`（C++ 运行库） | 全新系统或未装过 VC++ 运行库 |
| Universal C Runtime (UCRT) | `ucrtbase.dll` / `api-ms-win-crt-*` | Windows 7 未打 KB2999226 时（本软件已 app-local 内置，一般无需） |
| DirectX 运行时 | `d3dcompiler_47.dll`（Qt ANGLE 后端，可选） | 精简系统 / 未装 DirectX |

## 支持的系统

- Windows 7 **SP1**（x86 / x64）
- Windows 8 / 8.1（x86 / x64）
- Windows 10（x86 / x64）
- Windows 11（x64 / Arm 上以 x64 模拟运行）

> Windows 7 必须为 **SP1**，且建议安装 SHA-2 支持更新（KB4474419），否则较新的
> VC++ 运行库可能无法安装。检测脚本在 Win7 上会改用 VS2019 版运行库以降低要求。

## 使用方式

### 方式一：启动器（推荐）
双击 **`Launch.bat`**：先运行 `bootstrap.ps1` 检测并安装缺失运行库，然后启动 `LiumingClassroom.exe`。

### 方式二：应用内自检
直接运行 `LiumingClassroom.exe`，启动时会调用 `dep_check.check_runtime()`；
若缺组件，会弹窗提示并可**自动安装**。

### 方式三：命令行
```
dep_check.py            # 仅检测并打印报告
dep_check.py --json     # JSON 报告
dep_check.py --auto     # 检测并自动安装（可能弹 UAC）
```

## 实现说明

- `dep_check.py`：跨版本检测（`6.1` Win7 / `6.2` Win8 / `6.3` Win8.1 / `10.0` Win10、`build>=22000` Win11）
  与位数（x86/x64）识别；通过 `LoadLibrary` + 目录查找判断依赖；安装时按系统选择
  `vc_redist` 版本（Win7 用 VS2019），必要时经 UAC 提权。
- `bootstrap.ps1`：兼容 Windows PowerShell 2.0（Win7 自带），供 `Launch.bat` 预检调用。
- 安装器来源均为微软官方地址（`aka.ms/vs/...`、`download.microsoft.com`），下载到临时目录后静默执行
  （`/install /quiet /norestart`）。

> 若目标机器无外网，可把对应的 `vc_redist.x86.exe` / `vc_redist.x64.exe` 放到程序目录，
> 启动器会优先使用同目录下的同名安装包（如存在）。
