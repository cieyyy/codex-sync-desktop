# Codex Sync Desktop

一个轻量的 Windows/macOS 桌面工具，用 GitHub 私有仓库同步 Codex 对话文本，并修复目标设备的侧栏索引。

## 能做什么

- 扫描 `sessions` 和 `archived_sessions`
- 导出完整文字会话，包括推理、命令、工具调用、工具输出和任务状态
- 保留 Token、密钥、连接串和其他敏感字段，仅移除媒体及附件二进制
- 使用 SHA-256 清单验证同步文件
- 只追加缺失会话；同名不同内容按语义内容和时间合并
- 合并前把本机原文件和传入副本分别保存到备份与冲突目录
- 重建 `state_*.sqlite` 的 `threads` 记录及 `session_index.jsonl`
- 保留已有任务标题，并支持 Windows/macOS 项目路径映射
- 修改数据库前使用 SQLite Backup API 创建一致性备份
- 从界面回滚索引数据库和索引文件
- 调用系统 Git 和 GitHub CLI 拉取、提交及推送同步仓库

## 设计边界

GitHub 同步内容是去除图片和附件二进制后的完整文字记录。工具调用、工具输出、内部推理和敏感字段都会上传；仓库必须保持私有，并按生产密钥仓库的标准控制访问权限。

本地备份保留索引数据库，默认不会复制体积较大的附件和图片目录。独立的 `auth.json` 不会上传，但会话文字中出现的 API Key、Token 或密码会被保留。

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

当前发布包使用临时签名，没有 Apple Developer/Windows 商业代码签名。macOS
首次打开时可在 Finder 中右键应用并选择“打开”；Windows 可能显示 SmartScreen
提示，应先核对下载来源和 Release 校验信息再选择运行。

## 安全说明

- 只使用私有 GitHub 仓库存放会话。
- 推送前必须确认仓库为私有仓库，并检查所有协作者、部署密钥和访问 Token。
- 不要把 `.codex` 整个目录提交到 Git。
- 回滚前必须退出 Codex、ChatGPT 和 Codex++。

## 许可证

MIT
