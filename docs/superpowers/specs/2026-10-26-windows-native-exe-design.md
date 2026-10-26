# Windows 原生 EXE 发布设计

## 目标

为 Claude 切换器增加可直接下载安装的 Windows 原生发行物，同时保留现有 PowerShell 脚本作为兼容回退层：

- 发布 `ClaudeSwitcher-<version>-windows-setup.exe`（Inno Setup 安装包）。
- 安装包内包含 `ClaudeSwitcher.exe`（.NET 8 WPF 自包含单文件程序）。
- 继续发布现有 `ClaudeSwitcher-<version>-windows.zip`，供便携/排障使用。
- macOS 继续发布 `.app`、`.dmg`、`.zip`；macOS 不使用 `.exe`，本设计不改变 macOS 安装方式。

## 背景与现状

当前 `windows/` 只有 PowerShell 核心、PowerShell WPF 界面、安装脚本和保镖脚本，没有 C# 工程、安装包工程或 Windows CI 构建任务。现有 `install.ps1` 负责：

1. 探测代理客户端和出口国家。
2. 将核心脚本安装到 `%USERPROFILE%\.claude-switcher\`。
3. 写入 `PROXY_MODE`、`COUNTRY_TARGET`、`TZ_TARGET`、`PROXY_GROUP`。
4. 配置置顶规则、时区、IPv6、DNS 和保镖计划任务。
5. 创建桌面快捷方式。

现有 `SwitcherUI.ps1` 已实现 14 项检查、账号 A/B 切换、一键修复的界面逻辑，但依赖 `powershell.exe` 启动。原生 EXE 不应复制核心业务逻辑，否则两套实现会漂移。

## 方案比较

### 方案 A：原生 WPF + 自包含单文件 + Inno Setup（采用）

- 优点：用户无需预装 .NET；界面是真正 Windows 原生程序；现有 PowerShell 核心继续作为唯一业务逻辑；安装包可处理管理员配置。
- 成本：需要新增 C# 工程、测试工程和安装包构建脚本。
- 风险：WPF 界面需要与现有 PowerShell UI 行为保持一致。

### 方案 B：仅把 PowerShell UI 包装成 EXE

- 优点：改动最少，开发快。
- 缺点：EXE 只是启动器，仍依赖 PowerShell；用户感知和可维护性没有真正提升；后续签名、安装和错误处理仍不完整。

### 方案 C：把所有核心逻辑迁移到 C#

- 优点：长期可以摆脱 PowerShell 依赖。
- 缺点：迁移面大，账号切换、代理探测、计划任务和系统配置风险高；与 macOS/Linux 核心继续分叉，不适合本次迭代。

**结论：采用方案 A。** 原生 EXE 只负责界面和进程调用，所有安全检查、账号切换、系统修复仍由已安装的 `claude-switch.ps1` 执行。

## 架构

```text
ClaudeSwitcher-Setup.exe (Inno Setup, 管理员)
  ├─ ClaudeSwitcher.exe (.NET 8 WPF, self-contained, win-x64)
  ├─ install.ps1 (非交互安装入口)
  ├─ claude-switch.ps1 (已配置的核心脚本)
  ├─ claude-bodyguard.ps1
  └─ SwitcherUI.ps1 (兼容回退界面)
        │
        └─ ClaudeSwitcher.exe
             └─ powershell.exe -NoProfile -ExecutionPolicy Bypass
                  -File %USERPROFILE%\.claude-switcher\claude-switch.ps1
                  <command> [A|B]
```

### 进程边界

- `ClaudeSwitcher.exe` 不读取、复制、移动或删除账号目录内容。
- 账号目录只由 `claude-switch.ps1` 的既有逻辑操作。
- EXE 只允许调用以下命令：
  - `checkdetail`
  - `status`
  - `fix`
  - `switch A`
  - `switch B`
- `switch` 的目标在 UI 层和客户端层都必须限制为 `A` 或 `B`，不能把用户输入拼进命令。
- 使用 `ProcessStartInfo.ArgumentList`（或等价的安全参数传递方式）启动 PowerShell，禁止拼接未转义字符串。
- 子进程使用隐藏窗口、UTF-8 输出捕获和超时控制；超时后终止子进程并向 UI 报告失败，不能把超时误判为通过。
- `checkdetail` 输出必须完整解析 14 个唯一检查项；缺失、重复、未知或格式错误的输出一律视为失败，不得显示绿色。

### 输出解析

现有核心输出行格式为：

```text
<检查项>=<ok|warn|fail>:<详情>
```

解析规则：

- 只接受 `=` 后的状态为 `ok`、`warn`、`fail`。
- 只接受 14 个已定义的检查项。
- 同一检查项重复出现视为格式错误。
- 少于 14 项、缺少任一必需项或出现未知项时，整体检查结果为“不完整/失败”。
- `warn` 不视为全绿；界面显示黄色警告并禁止自动宣称环境安全。
- `fail`、解析错误、进程退出码非零、超时均视为阻断。

## 用户界面

首版保持现有 Windows 版信息架构：

- 顶部：标题、环境状态徽标。
- 中部：14 项检查列表，显示名称、详情、状态图标。
- 账号区：当前账号、账号 A、账号 B。
- 操作区：重新检查、一键修复。
- 失败提示：显示可操作错误，不显示敏感 IP 或代理凭据。

行为：

- 启动后自动执行 `checkdetail`。
- 检查期间禁用账号切换和修复按钮，避免并发操作。
- 账号切换成功后重新检查。
- 修复完成后重新检查。
- 核心脚本缺失时显示安装/重新安装提示，不自动创建或下载脚本。
- 退出时只退出界面，不主动结束 Claude。

## 安装与打包

### 原生程序

- 目标框架：`net8.0-windows`。
- 发布配置：`win-x64`、`SelfContained=true`、`PublishSingleFile=true`。
- 发布目录只包含运行所需文件；WPF 资源（图标）随安装包分发。
- 不要求用户安装 .NET Runtime。

### Inno Setup

- 安装包名称：`ClaudeSwitcher-<version>-windows-setup.exe`。
- 安装器需要管理员权限，因为会注册计划任务、设置时区、关闭 IPv6 和修改系统 DNS 缓存。
- 安装器调用 `install.ps1` 的非交互模式完成系统配置，然后创建开始菜单/桌面快捷方式指向 `ClaudeSwitcher.exe`。
- 卸载时删除安装目录和快捷方式；是否删除 `%USERPROFILE%\.claude-switcher` 中的账号存档必须明确提示，默认保留账号数据，避免误删。
- 不运行任何需要人工输入的 `Read-Host` 或 `pause` 路径。

### `install.ps1` 非交互参数

新增可选参数，保持默认交互行为兼容：

- `-NonInteractive`：不等待输入，不执行 `pause`；无法自动识别代理客户端时返回非零退出码。
- `-ProxyMode <auto|clash-verge|sing-box|clashx|surge|wireguard|other>`：由安装器显式传入探测结果。
- `-CoreSource <path>`：供安装包指定随包附带的核心脚本目录，避免依赖当前工作目录。
- `-SkipLaunch`：安装完成后不启动 Claude，供自动化构建和 CI 使用。

所有参数都必须有明确默认值；现有直接双击运行的路径保持兼容。

## 构建与 CI

### 新增脚本

- `scripts/package-windows.ps1`：
  - 校验版本号只包含安全字符。
  - 还原并运行 .NET 测试。
  - 发布自包含单文件 `win-x64`。
  - 调用 Inno Setup 编译安装包。
  - 将产物写入 `build/`，并检查关键文件存在。
- 保留 `scripts/package-macos.sh` 不变。

### GitHub Actions

- 现有 macOS job 继续负责 `.app`、`.dmg`、macOS zip、Linux tar.gz 和脚本包。
- 新增 `windows-latest` job：
  - 安装 .NET 8 SDK。
  - 还原并测试 Windows C# 工程。
  - 安装/使用 Inno Setup。
  - 构建 `ClaudeSwitcher-<version>-windows-setup.exe`。
  - 将安装包和现有 Windows 脚本 zip 作为 release asset 上传。
- Release checksums 必须同时覆盖 Windows 安装包、Windows 脚本 zip、macOS 产物和 Linux 产物。
- 如果 Inno Setup 在 runner 上不可用，构建必须失败而不是静默跳过；发布不得缺少 Windows EXE。

## 安全与失败策略

- 不读取、打印或记录用户的 IP、Cookie、账号凭据或代理密钥。
- 不在检查不完整时显示“环境安全”。
- 不把 PowerShell 的 stderr 静默当作成功；记录可读错误摘要，但不回显敏感信息。
- 不绕过现有 `claude-switch.ps1` 的地区/代理/账号检查。
- 不把 `switch` 参数直接交给 shell 字符串拼接。
- 测试和本地构建不得调用安装器，也不得修改维护者已安装版本。

## 测试策略

### C# 单元测试

至少覆盖：

1. 合法的 14 项输出全部解析成功。
2. `warn` 不产生全绿状态。
3. `fail` 阻断。
4. 缺少检查项导致不完整/失败。
5. 重复项导致失败。
6. 未知项导致失败。
7. 格式错误的行导致失败。
8. 进程退出码非零导致失败。
9. 超时导致失败并终止进程。
10. `switch` 只接受 `A`/`B`，拒绝其他目标。
11. 命令参数通过参数列表传递，不拼接到单个字符串。
12. 核心脚本不存在时返回可操作的安装错误。

### 构建验证

- `dotnet test windows/ClaudeSwitcher.App.Tests`
- `dotnet publish windows/ClaudeSwitcher.App -c Release -r win-x64 --self-contained true /p:PublishSingleFile=true`
- Inno Setup 编译成功并产出安装包。
- 安装包不启动真实安装流程；仅在 CI/隔离临时目录验证文件清单和版本信息。

### 回归

- 现有 `bash -n`、Python 测试、Swift 构建、JavaScript 语法和 `SHA256SUMS` 检查保持通过。
- Windows PowerShell 文件修改后必须保持 UTF-8 with BOM。
- 修改 `core/`、`daemons/` 或 `installer/` 时重新运行 `scripts/gen-sums.sh`；本次如未改动这些目录，不改动 `SHA256SUMS`。

## 非目标

- 不在本次迁移 macOS `.app`/`.dmg` 构建方式。
- 不生成 macOS `.exe`。
- 不把账号快照逻辑迁移到 C#。
- 不新增 Windows 自动更新机制。
- 不改变现有账号目录结构和安全红线。

## 验收标准

1. Windows 原生项目能在 Windows x64 上 `dotnet test` 和 `dotnet publish` 成功。
2. `ClaudeSwitcher.exe` 能在没有 .NET Runtime 的 Windows 10/11 x64 环境启动。
3. Inno Setup 产出 `ClaudeSwitcher-<version>-windows-setup.exe`。
4. 安装包安装后的快捷方式指向原生 EXE，且 EXE 能调用已安装的核心脚本完成检查、切换 A/B 和修复。
5. 核心输出不完整、超时或退出码异常时，界面不得显示绿色。
6. Release workflow 同时发布 Windows 安装包和现有 Windows 脚本 zip。
7. macOS 构建与发布产物不回归。
8. 维护者本机的已安装版本不被修改。