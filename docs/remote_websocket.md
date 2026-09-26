# 远程配置 WebSocket 协议

本协议用于让 **服务端** 通过 WebSocket 长连接，随时读取 / 修改 LiumingClassroom 的配置。
客户端实现见 `remote_config.py`（基于 `PyQt5.QtWebSockets.QWebSocket`，随 Qt 事件循环运行，无需额外线程）。

- **client**：LiumingClassroom 客户端
- **server**：你的服务端

---

## 1. 客户端配置

在 `config/config.ini` 的 `[Remote]` 节中配置（默认值见 `data/default_config.json`）：

| 键 | 说明 | 默认 |
| --- | --- | --- |
| `enabled` | `1` 启用远程配置连接 | `0` |
| `url` | WebSocket 地址，如 `ws://127.0.0.1:8765/ws` 或 `wss://...` | `""` |
| `token` | 鉴权令牌（在 `hello` 中发送） | `""` |
| `auto_reconnect` | 断开后自动重连 | `1` |
| `reconnect_interval` | 重连间隔（秒） | `5` |

> 注意：`enabled` / `url` / `token` 本身也可被远程修改，但修改后需重连才生效。

---

## 2. 连接与鉴权

客户端连接成功后，立即发送：

```json
{ "type": "hello", "protocol": 1, "app": "LiumingClassroom", "token": "<token>" }
```

服务端校验后可回复：

```json
{ "action": "auth", "ok": true }
```

鉴权失败则回复（客户端会记录日志并断开）：

```json
{ "action": "auth", "ok": false, "error": "invalid token" }
```

> 若服务端不回复 `auth`，客户端不做强制拦截（便于内网无鉴权使用）；如需强制，请在服务端拒绝非法连接。

---

## 3. 通用消息格式

- **服务端 → 客户端（请求）**：带 `id`（任意类型，建议整数或字符串）与 `action`。
- **客户端 → 服务端（响应）**：`{ "id": <原样返回>, "ok": true|false, "data": ..., "error": ... }`
- 无 `id` 的消息（如 `notify`）客户端不回响应。
- 帧为 **JSON 文本帧**（`sendTextMessage`）。

---

## 4. action 列表

### 4.1 `ping`
请求：`{ "id": 1, "action": "ping", "time": 1727000000 }`
响应：`{ "id": 1, "ok": true, "data": { "pong": 1727000000 } }`

### 4.2 `get` — 读取配置
读取单个键：`{ "id": 2, "action": "get", "section": "General", "key": "theme" }`
读取整个节（`key` 省略或为空）：`{ "id": 2, "action": "get", "section": "General" }`
响应：`{ "id": 2, "ok": true, "data": "default" }`

### 4.3 `set` — 修改单个配置
```json
{ "id": 3, "action": "set", "section": "General", "key": "opacity", "value": "80" }
```
响应：`{ "id": 3, "ok": true }`
写入成功后客户端会 **热重载**（见第 6 节）。

### 4.4 `set_many` — 批量修改
```json
{ "id": 4, "action": "set_many", "items": [
  { "section": "General", "key": "opacity", "value": "80" },
  { "section": "General", "key": "margin", "value": "20" }
] }
```
响应：`{ "id": 4, "ok": true, "data": { "changed": ["General.opacity", "General.margin"], "failed": [] } }`

### 4.5 `reload` — 触发一次热重载
`{ "id": 5, "action": "reload" }` → `{ "id": 5, "ok": true }`

### 4.6 `lock` / `unlock` / `locks` — 仅允许远程修改
锁定后，**本地（设置界面 / 程序内部）写入会被拒绝**，只有远程 `set` 能改写。

```json
{ "id": 6, "action": "lock", "keys": ["General.theme", "TTS.enable"] }
```
```json
{ "id": 6, "action": "unlock", "keys": ["General.theme"] }
```
```json
{ "id": 6, "action": "locks" }
```
响应：`{ "id": 6, "ok": true, "data": { "locked": ["General.theme", "TTS.enable"] } }`

- 支持 `"Section.*"` 锁定整个节。
- 锁定状态持久化到 `config/remote_lock.json`。

### 4.7 `duty_get` / `duty_set` — 值日生配置
- `{ "id": 7, "action": "duty_get" }` → `data` 为 `config_to_dict(DutyConfig)` 的结果（见 `duty.py`）。
- `{ "id": 7, "action": "duty_set", "config": { ... } }`：用 `config_from_dict` 覆盖并保存到 `config/duty.json`，随后热重载。

### 4.8 `ota` — 远程下发更新（静默安装并重启）

后端下发更新包地址，客户端**自动下载 → 校验 → 静默安装 → 重启**（无需用户确认）。
该功能取代了原内置更新服务器（原“检查更新”已停用）。

```json
{ "id": 8, "action": "ota", "url": "https://.../LiumingClassroom-Windows-x64.zip",
  "version": "1.2.0", "sha256": "<可选，强烈建议>" }
```

响应：`{ "id": 8, "ok": true, "data": { "started": true, "version": "1.2.0" } }`

- `url`：更新包直链。以 `.zip` 结尾时会等待本进程退出后解压覆盖安装目录并重启；否则视为可执行安装器，分离运行后退出。
- `sha256`：可选但**强烈建议**；校验失败会中止安装。
- 需要程序以“非便携/可写”方式安装，且对安装目录有写权限。

### 4.9 `notify` — 服务端推送通知（无响应）
```json
{ "action": "notify", "state": 1, "title": "通知标题", "subtitle": "副标题",
  "content": "正文", "lesson_name": "", "duration": 5000 }
```

- 加上 `"special": true` 时，客户端会显示**顶部横幅特别通知**（更醒目、需手动关闭）。

---

## 5. 支持的配置节

`config.ini` 的节：`General` `Toast` `TTS` `Weather` `Color` `Plugin` `Time` `Date` `Audio` `Temp` `Version` `Other` `Remote`
键值以 **字符串** 形式读写；读取时会按 `default_config.json` 的类型自动转换。

---

## 6. 热重载范围

远程 `set` / `set_many` / `reload` / `duty_set` 后，客户端会调用 `main.apply_remote_reload()`：

1. 重新读取 `config.ini`；
2. 重新加载值日生配置（`duty.json`）；
3. 刷新桌面小组件。

> 主题切换、字体等需要重建窗口的改动，建议服务端修改后调用 `restart`（尚未实现）或提示用户重启才能完全生效。

---

## 7. 安全建议

远程配置通道能力很强，务必至少做到：

1. 使用 `wss://` 加密连接；
2. 配置并强制校验 `token`；
3. 仅在内网 / 可信网络开放；
4. 用 `lock` 把关键项（如 `safe_mode`、`Plugin.auto_enable_plugin`）设为远程独占，避免本地被误改。

---

## 8. 打包（PyInstaller）注意

`remote_config.py` 依赖 `PyQt5.QtWebSockets`。PyInstaller 会自动收集该模块，但若打包后运行报
`ModuleNotFoundError: No module named 'PyQt5.QtWebSockets'` 或缺少 `Qt5WebSockets.dll`，
请在打包命令中追加：

```
--hidden-import PyQt5.QtWebSockets
```

（`config.ini` 的 `[Remote]` 节由 `data/default_config.json` 提供默认值，打包时会随 `data` 一起收集。）

---

## 9. 协议 v2 扩展：全量快照与批量应用（云端权威）

> v2 由主站（流明）作为**权威状态源**提供云端校务管理：团队中获授权成员可在网页上修改本机「一切配置」（含课表本体、值日生、学科库、小组件、插件等），并留存变更历史。
> 客户端在 `hello` 中声明 `"protocol": 2`；服务端可据此启用下述 action。v1 客户端不受影响。

### 9.1 `snapshot` — 回传全量文档

请求：`{ "id": 20, "action": "snapshot" }`

响应 `data`：

```json
{
  "config": { "General": { "schedule": "新课表 - 1.json" }, "Toast": { }, "TTS": { } },
  "schedules": { "新课表 - 1.json": { "part": {}, "part_name": {}, "timeline": {}, "timeline_even": {}, "schedule": {}, "schedule_even": {} } },
  "active_schedule": "新课表 - 1.json",
  "duty": { "enabled": false, "students": [], "mode": "id_rotation" },
  "subjects": { "subject_icon": {}, "subject_abbreviation": {}, "subject_list": [] },
  "widgets": ["widget-weather.ui", "widget-countdown.ui"],
  "plugins": { "enabled": ["..."], "installed": ["..."] },
  "client_version": "1.2.0"
}
```

- `config` **不含** `Remote` 节（连接参数，避免自断连）；其余节全量。
- `schedules` 为 `config/schedule/*.json` 中除 `backup.json` 外的全部文件。
- `plugins.installed` 只读（来自 `plugins_from_pp.json`）。

### 9.2 `apply` — 批量落盘并热重载

请求：

```json
{
  "id": 21,
  "action": "apply",
  "bundle": {
    "config": { "General": { "theme": "default" } },
    "schedules": { "新课表 - 2.json": { } },
    "active_schedule": "新课表 - 2.json",
    "duty": { },
    "subjects": { },
    "widgets": ["widget-duty.ui"],
    "plugins": { "enabled": ["xxx"] }
  },
  "delete_schedules": ["旧课表.json"]
}
```

- `bundle.config[节][键] = 值`：写 `config.ini`，`source='remote'`（可覆盖被 `lock` 的项）；`Remote` 节忽略。
- `bundle.schedules[文件名] = 内容`：写 `config/schedule/<文件名>`。
- `delete_schedules`：删除课表文件（当前活动课表不会被删）。
- `bundle.active_schedule`：切换当前课表（等价写 `General.schedule`）。
- `duty` / `subjects` / `widgets` / `plugins.enabled` 覆盖对应文件。
- 所有字段可选，只处理出现的字段。

响应：`{ "id": 21, "ok": true, "data": { "applied": ["config.General", "schedule:新课表 - 2.json", "duty"], "failed": [] } }`

落盘后调用 `apply_remote_reload()` —— **v2 起该函数会同时热重载课表**（此前仅重载 `config.ini`、值日生与小组件）。

### 9.3 重连对齐（权威在服务端）

1. 客户端连上并发 `hello`（`protocol: 2`）→ 服务端回 `auth`。
2. 服务端请求 `snapshot` 获取客户端现状。
3. 逐文档按 `revision` 比对：
   - 服务端更新 → 下发 `apply` 覆盖客户端；
   - 客户端本地领先（疑似本地改动）→ 记入服务端留档（`action=local_override`），随后仍以服务端为准；
   - 服务端无文档（首次接入）→ 以客户端 `snapshot` 种子化（`action=seed`）。
4. 之后服务端的任何写入，在线时即时通过 `apply` 下发；离线则下次上线自动对齐。

