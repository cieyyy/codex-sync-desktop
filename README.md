# Codex Sync Desktop

一个轻量的 Windows/macOS 桌面工具，用 GitHub 私有仓库同步 Codex 对话文本，并修复目标设备的侧栏索引。

## 能做什么

- 扫描 `sessions` 和 `archived_sessions`
- 默认只导出用户/助手文本及最小会话元数据
- 移除媒体、附件、工具调用、内部推理和常见凭据
- 使用 SHA-256 清单验证同步文件
- 只追加缺失会话，不覆盖同名不同内容的本机会话
- 把冲突副本放入 `~/.codex/import-conflicts`
- 重建 `state_*.sqlite` 的 `threads` 记录及 `session_index.jsonl`
- 保留已有任务标题，并支持 Windows/macOS 项目路径映射
- 修改数据库前使用 SQLite Backup API 创建一致性备份
- 从界面回滚索引数据库和索引文件
- 调用系统 Git 和 GitHub CLI 拉取、提交及推送同步仓库

## 设计边界

GitHub 同步内容是可浏览的脱敏文本副本，不是原始运行状态的完整克隆。工具调用、附件、图片、加密内容和内部推理不会上传，因此导入任务适合搜索、查看和继续交接，但不能保证恢复原任务的全部执行上下文。

本地备份保留索引数据库，默认不会复制体积较大的附件和图片目录，也不会上传 `auth.json`、API Key 或其他认证文件。

## 源码运行

要求 Python 3.9+ 和 Tk 8.6+，推荐 Python 3.11。macOS 自带的旧 Tk 8.5
可能无法在新系统上创建窗口；普通使用者应直接下载构建好的 `.app`/DMG，
其中已包含兼容的 Python/Tk 运行库。

```bash
python3 -m codex_sync_desktop
```

只读诊断：

```bash
python3 -m codex_sync_desktop --diagnose
```

运行测试：

```bash
python3 -m unittest discover -v
```

## 第一次使用

1. 安装 Git 和 GitHub CLI，并运行 `gh auth login`。
2. 在“设置”中选择本机 `~/.codex`、本地同步仓库路径及 GitHub 仓库地址。
3. 点击“初始化/克隆仓库”。
4. 在源设备点击“导出并推送”。
5. 在目标设备选择来源设备，先“预览导入”。
6. 完全退出 Codex、ChatGPT 和 Codex++，再点击“导入并修复侧栏”。

应用自身可以保持运行；它会阻止在其他相关程序仍占用数据库时执行修复或回滚。

## 构建产物

GitHub Actions 会构建：

- Windows x64 ZIP
- macOS Intel ZIP/DMG
- macOS Apple Silicon ZIP/DMG

源码运行没有第三方依赖。PyInstaller 仅在 GitHub Actions 构建机安装，不占用使用者本机开发磁盘。

## 安全说明

- 只使用私有 GitHub 仓库存放会话。
- 推送前仍应抽查首次导出的内容，自动脱敏无法覆盖所有私有数据格式。
- 不要把 `.codex` 整个目录提交到 Git。
- 回滚前必须退出 Codex、ChatGPT 和 Codex++。

## 许可证

MIT
