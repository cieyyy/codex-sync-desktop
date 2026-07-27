# Codex Sync Desktop

一个轻量的 Windows/macOS 桌面工具，用 GitHub 私有仓库同步 Codex 对话文本，并修复目标设备的侧栏索引。

## 能做什么

- 只扫描活动的 `sessions`；归档和已删除会话不再上传
- 导出完整文字会话，包括推理、命令、工具调用、工具输出和任务状态
- 保留 Token、密钥、连接串和其他敏感字段，仅移除媒体及附件二进制
- 使用 SHA-256 清单验证同步文件
- 同步 SQLite／侧栏索引中的任务名称，导入时所选来源设备的非空标题优先
- 每次导出只清理当前设备 Git 目录中已经归档或删除的旧副本，不删除其他设备现有任务
- 只追加缺失会话；内容不同的同一会话在后台按语义内容和时间自动合并
- 不再生成单独的冲突副本，也不在界面显示冲突列表
- 重建 `state_*.sqlite` 的 `threads` 记录及 `session_index.jsonl`
- 保留已有任务标题和会话中的原始项目路径，不需要路径映射
- 每次导入前创建完整事务撤销点，包含被合并会话、状态数据库和侧栏索引
- 默认只保留最近一次撤销点；可一键撤销最近导入或清理全部历史备份
- 日志自动轮转并限制为约 2 MiB，可一键清理
- 推送连接中断时自动切换 HTTP/1.1 重试，并继续推送上次遗留的本地提交
- 调用系统 Git 和 GitHub CLI 拉取、提交及推送同步仓库

## 设计边界

GitHub 同步内容是去除图片和附件二进制后的完整文字记录。工具调用、工具输出、内部推理和敏感字段都会上传；仓库必须保持私有，并按生产密钥仓库的标准控制访问权限。

本地撤销点只保存导入所需的会话原文件、索引数据库和索引文件，不复制附件和图片目录。独立的 `auth.json` 不会上传，但会话文字中出现的 API Key、Token 或密码会被保留。

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
2. 在“日志与设置”中选择本机 `~/.codex`、本地同步仓库路径及 GitHub 仓库地址。
3. 点击“初始化/克隆仓库”。
4. 在源设备点击“导出并推送”。
5. 在目标设备选择来源设备，先“预览导入”。
6. 完全退出 Codex、ChatGPT 和 Codex++，再点击“导入并修复”。

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
- 导入和撤销前必须退出 Codex、ChatGPT 和 Codex++。
- 一键清理备份会永久移除撤销能力，界面会在执行前再次确认。

## 许可证

MIT
