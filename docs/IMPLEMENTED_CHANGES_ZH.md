# Codex Sync Desktop 已实施修改记录

> 文档日期：2026-08-04
> 核对依据：当前源码、自动测试、设计规范和 Git 提交历史  
> 说明：本文区分“已发布”“已进入 Beta”“仅在本地源码完成”。

## 1. 当前版本状态

| 层级 | 版本或提交 | 状态 |
|---|---|---|
| 远程稳定版 | `v0.7.1` / `4bd4d7b` | 已发布 |
| 手工测试版 | `manual-v0.7.2-beta.6` / `56687d1` | 已发布，未使用 Actions |
| 当前发布候选 | `manual-v0.7.2-beta.7` | 全新设备仓库恢复、跨平台哈希、设备显示名和开源文档 |
| Python 包版本 | `0.7.2b7` | Beta 7 候选 |
| 当前自动测试 | 133 项 | 全部通过 |

Beta 3 相对远程稳定版包含的主要提交：

```text
64a193c  完整导入预览，不再截断
ae40ea8  首次配置和拉取恢复增强
342a88c  顶部活动状态增加横向滚动
18d8c12  拉取前自动修复 GitHub 访问
821f33b  全新设备默认浏览器 GitHub 登录
e6076fa  软件总体方案与已实施修改文档
3ad5dff  Beta 3 版本整理
```

## 2. 初始同步能力

### 已实施

- 创建 Windows/macOS Tkinter 桌面应用。
- 读取 Codex JSONL 会话。
- 按设备目录导出到 GitHub 私有仓库。
- 使用 manifest 和 SHA-256 校验同步文件。
- 导入后修复 SQLite 和侧栏索引。
- 关闭 SQLite 连接，避免 Windows 文件占用。
- 备份时保留数据库嵌套路径。
- 识别原始会话和去媒体后的等价会话。

相关早期提交：

```text
d3e1536  add cross-platform Codex sync desktop app
7ad7ac0  close SQLite handles on Windows
ec95bfc  preserve nested database paths in backups
cba4098  detect equivalent sanitized conversations
3b627ec  find Homebrew tools from macOS app
```

## 3. 完整文字同步和冲突合并

### 已实施

- 保留用户消息、助手消息、命令、工具调用、工具输出、任务状态和推理文字。
- 保留会话文字内 Token、密钥、密码和连接串。
- 删除图片、附件二进制、Data URL 和超长媒体块。
- 根据实际内容和时间合并同一会话差异。
- 本机内容已经包含来源内容时不产生冲突。
- 不再把内容不同简单视为同名重复或只按 Task ID 覆盖。
- 后台自动合并，不要求用户处理冲突文件。

主要提交：

```text
dca9e83  sync complete text and merge conflicts
3396357  simplify sync UI and add transactional imports
```

## 4. 活动会话、归档和删除

### 已实施

- 导出只扫描活动 `sessions`。
- 本机归档或删除后，下次导出会清理当前设备在仓库中的旧副本。
- 不会因为某一设备导出而删除其他设备目录。
- 活动目录暂时不可用时，不会误清空仓库中已有导出。

主要提交：

```text
3a3e4c8  sync active sessions and task titles
```

### 尚未实施

- 在预览窗口勾选某个会话并生成跨设备永久排除规则。
- 已经从某一设备删除的会话，在其他设备仍保留活动副本时自动全局删除。

因此，当前“停止同步”是当前设备导出范围规则，不是跨设备删除墓碑。

## 5. 标题同步与错误标题修复

### 已实施

- 从有效状态数据库和 `session_index.jsonl` 读取人工标题。
- 来源设备有效非空标题可以更新目标设备标题。
- 预览窗口可以修改最终导入标题。
- 标题草稿按来源设备和 Task ID 暂存，并在重新生成导入计划后继续生效。
- 同时更新数据库中的 `title`、可用的 `name` 字段和侧栏索引。
- 拒绝把 `AGENTS.md instructions`、`environment_context` 等注入上下文当标题。
- 附件前言之后的真实用户请求可以作为候选标题。
- 保留本机已经存在的有效人工标题。

主要提交：

```text
41d4a90  preserve human titles and ignore injected context
826e726  add editable import preview
```

## 6. SQLite 和侧栏索引修复

### 已实施

- 自动选择现代 Codex 状态数据库，兼容旧数据库。
- 为缺失任务插入 `threads` 记录。
- 更新 rollout 路径、时间、项目目录、标题、名称和预览字段。
- 重建 `session_index.jsonl`。
- 重复 Task ID 时选择内容更丰富的活动记录。
- 修复重复索引时避免 `UNIQUE constraint failed: threads.id`。
- 导入文件已存在但索引修复曾中断时，下一次同步仍会重试索引修复。

主要提交：

```text
42b2e00  make duplicate session index repair idempotent
```

## 7. 事务备份、撤销与清理

### 已实施

- 导入前保存会话、状态数据库和侧栏索引撤销点。
- 新增会话可以在未被后续修改时撤销。
- 被合并会话可以恢复导入前版本。
- 状态数据库和索引可以一起恢复。
- 默认仅保留最近一次撤销点。
- 一键清理同步备份、旧导入备份和旧差异副本。
- 清理前显示永久失去撤销能力的确认。
- 日志轮转为两个约 1 MiB 文件，并提供一键清理。

主要提交：

```text
3396357  simplify sync UI and add transactional imports
```

## 8. Git 拉取、推送与网络恢复

### 已实施

- 拉取使用 rebase 和 autostash。
- 缺少 upstream 时自动获取当前分支并建立跟踪。
- 空远程仓库视为可继续首次同步。
- 推送失败后即使工作树没有新变化，也继续推送遗留提交。
- HTTP/2 连接中断时自动使用 HTTP/1.1 重试。
- 拉取遇到 GitHub 认证、权限或 SSH 远端访问错误时：
  - 读取 `origin`；
  - 检查 GitHub CLI 登录；
  - 重新执行 `gh auth setup-git`；
  - 将 GitHub SSH 地址转换为 HTTPS；
  - 自动重试一次；
  - 失败时显示中文恢复路径。

主要提交：

```text
720c1e0  retry interrupted pushes over HTTP/1.1
ae40ea8  harden first-run setup and pull recovery
18d8c12  repair GitHub access before pull
```

## 9. 首次配置与全新设备支持

### 已实施

- 四步首次配置向导。
- 首次配置未完成时自动弹出向导。
- 向导相对主窗口居中并保持在应用表面。
- 检查 Git、GitHub CLI 和 GitHub 登录状态。
- 缺少工具时提供一键自动安装/修复。
- Windows 检查 PATH、标准目录、注册表、自定义 Git 安装目录和软件私有工具目录。
- Windows GitHub CLI 使用官方 ZIP 便携版，无需 MSI、管理员权限或系统 PATH。
- Git 缺失时优先使用 winget，失败后打开经过 SHA-256 校验的官方安装器。
- macOS 使用系统命令行工具安装器和官方 GitHub CLI universal.pkg。
- 安装完成后必须通过真实 `--version` 检测才显示成功。
- 工具下载只接受 GitHub 官方资源并校验 SHA-256。
- 检测到零会话且没有侧栏索引时视为正常空设备。
- 第 4 步明确区分“创建新的私有仓库”和“连接已有私有仓库”。
- 可列出当前账号有权限的私有仓库，也可手动输入 `owner/repository` 或 GitHub HTTPS 地址。
- 连接已有仓库时验证访问权限、私有性和本地 `origin` 是否匹配。
- 仅对无文件、无提交且缺少 `origin` 的空 Git 仓库自动补齐远程地址。
- 已有本地内容、提交或不同远程仓库时停止，避免错误改绑。
- 向导中间步骤区域支持纵向滚动，底部导航和进度区保持可见。
- 纵向滚动条采用深色高对比样式，仅在当前页面内容超出可见区域时显示。
- 页面切换、窗口缩放和表单展开后会重新检测溢出，内容重新放得下时自动隐藏滚动条。
- 页面无溢出时忽略鼠标滚轮，避免无意义滚动。

主要提交：

```text
eb789b6  add guided private repository onboarding
d35cc39  detect and repair broken sync tools
244205e  complete first-run customer onboarding
eb740b2  wait for Windows installer verification
a12e2c4  automate first-run tool installation
c17e3fc  make Windows path detection cross-platform
af2c8ae  detect custom Windows tool installations
b2e5e6c  install GitHub CLI without MSI
```

### 当前本地源码待发布

Beta 7 已完成：无本机会话但远端已有数据时直接引导导入；误选 GitHub ZIP 快照时自动转到安全克隆；设备下拉框显示 manifest 真实名称；Windows/macOS 换行转换不再造成整批哈希失败；中文设备名不再退化为 `device`。

## 10. 默认浏览器 GitHub 登录

### 当前本地源码已实施

- 全新设备无需提前登录 GitHub。
- 点击登录先显示居中安全说明。
- 自动检测并调用操作系统默认浏览器。
- 只允许自动打开 GitHub 官方 HTTPS 页面。
- GitHub CLI 使用网页设备授权和 HTTPS Git 协议。
- 尝试自动复制一次性验证码。
- 密码、邮箱验证和二次验证只在 GitHub 官方页面完成。
- 软件后台等待，不弹终端窗口。
- 浏览器未打开时提供“重新打开授权页”。
- 剪贴板不可用时自动去掉复制参数重试。
- 已经登录的设备跳过浏览器，直接修复 Git 凭据。
- 授权完成后复检 `gh auth status` 并执行 `gh auth setup-git`。

主要提交：

```text
821f33b  guide first-time GitHub browser login
```

### 发布状态

该功能已通过自动测试并随 Beta 3 发布。安装了 v0.7.1 或 v0.7.2 Beta 2 的设备仍然使用旧登录行为。

## 11. 代理和证书

### 已实施

- Windows 读取 WinINet 系统代理。
- macOS 读取 `scutil --proxy`。
- 探测常见本机 HTTP 代理端口。
- 不绑定 Clash 名称，可用于任何提供标准 HTTP 代理的工具。
- 拒绝保存包含账号密码的代理 URL。
- 构建包包含可信 CA 文件。
- 不通过关闭 TLS 校验掩盖证书问题。
- 代理设置应用到 Git、GitHub CLI 和 GitHub API 请求。

主要提交：

```text
75fae26  detect system proxies and bundle trusted CA
```

## 12. UI、进度和桌面集成

### 已实施

- UI 改为深海军蓝、电光青和宝蓝色科技风。
- 普通按钮不使用灰色和高饱和绿色。
- 同步、拉取、推送、导入、修复和工具安装显示进度。
- Windows 命令后台运行，不闪出终端。
- 主窗口使用融合界面的深色自绘标题栏。
- 更换统一同步图标。
- 移除鼠标点击后残留的浅蓝色/虚线焦点框，同时保留键盘可访问焦点。
- 修复 Windows 任务栏和 Alt+Tab 注册。
- 顶部活动状态提供横向滚动，可查看完整设备名和长进度文本。
- 操作结果只显示成功、数量、失败和原因，避免展示大量 Git 文件列表。

主要提交：

```text
0018410  redesign dark UI and show task progress
b6ff02d  replace green UI accents with high contrast cyan
d333846  hide command windows and refresh app chrome
29e4729  polish window focus and taskbar identity
4bd4d7b  restore Windows taskbar presence
342a88c  add scrollable activity status
```

设计规范保存在：

```text
design-system/codex-sync-desktop/MASTER.md
```

## 13. 导入预览

### 已实施

- 动作分类：新增、相同、自动合并、失败、标题更新。
- 点击动作打开居中的主从式预览窗口。
- 左侧选择会话，右侧显示元数据和完整文字。
- 自动合并可切换来源、本机和合并后三个版本。
- 预览不再按固定字符或固定记录数量截断。
- 只流式加载当前版本，切换时取消旧加载任务。
- 标题可以编辑并暂存。

主要提交：

```text
826e726  add editable import preview
64a193c  render complete import previews
```

### 尚未实施

- 在预览窗口直接删除/永久排除会话。
- 跨设备同步永久排除规则。
- 修改 JSONL 正文；当前正文保持只读以保护结构。

## 14. 发布和构建操作

### 已实施

- Windows x64 Setup.exe 和 Portable ZIP 构建。
- macOS Intel 和 Apple Silicon 构建配置。
- Release SHA-256 校验文件。
- v0.7.2 Beta 1、Beta 2 使用本地构建和手工上传，没有使用 GitHub Actions。
- 手工 Beta 使用独立分支和不匹配 `v*` 的标签，稳定版 `main` 和 v0.7.1 未被覆盖。

### 当前边界

- 安装包未购买 Windows 商业签名。
- macOS 未做 Apple Developer 公证。
- 最新两个本地提交尚未重新构建 Windows/macOS 包。
- GitHub Actions 工作流仍存在于仓库，但可以选择完全不使用。

## 15. 测试证据

截至当前本地提交：

```text
全量自动测试：133 项通过
Python compileall：通过
```

测试覆盖：

- Git/GitHub CLI 探测和安装降级。
- Windows 自定义安装路径。
- macOS 系统代理。
- 默认浏览器调用和非 GitHub 页面拦截。
- 全新设备、已登录设备和授权失败。
- 剪贴板不可用降级。
- Git 拉取 upstream、自愈和 HTTP/1.1 推送。
- 会话合并、标题、完整预览、索引修复、事务备份和撤销。
- Windows 窗口、任务栏和状态滚动组件。

## 16. 用户可见行为变化摘要

修改前：

- 需要用户理解 Git 命令和目录。
- 登录或工具缺失时容易卡住。
- 内容差异可能被当作冲突文件。
- 标题可能来自注入上下文。
- Git 输出过长，错误原因不清晰。
- 预览内容可能截断。
- Windows 可能闪终端、任务栏图标不稳定。

修改后：

- 首次配置按四步向导完成。
- 缺失工具自动准备。
- 浏览器完成 GitHub 账号、密码和二次验证。
- 同一会话按内容和时间自动合并。
- 标题可预览、修改并同步。
- 导入前有完整预览和撤销点。
- 日志、备份和界面结果受控。
- Windows/macOS 日常同步不要求输入 Git 命令。

## 17. 后续建议顺序

1. 将当前源码升为新的 Beta 版本。
2. 本地构建 Windows、Intel Mac、Apple Silicon Mac，不使用 Actions。
3. 在真正从未登录 GitHub 的三类设备上验证浏览器授权。
4. 验证私有仓库首次创建、拉取、推送和二次验证。
5. 实现“预览选择并永久排除会话”的跨设备墓碑机制。
6. 增加仓库体积统计和安全清理建议，但不自动重写 Git 历史。
7. 完成商业代码签名和 Apple 公证后再提升为稳定版。
