# Contributing

感谢参与 Codex Sync Desktop。提交代码前请先确认改动不会扩大用户会话、凭据或本地数据库的暴露范围。

## 开发流程

1. Fork 仓库并从 `main` 创建功能分支。
2. 使用虚构或脱敏的 JSONL、SQLite 和 manifest 样例复现问题。
3. 保持修改范围清晰，并为行为变化添加测试。
4. 运行：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q codex_sync_desktop tests
git diff --check
```

5. 在 Pull Request 中说明用户可见变化、风险、数据迁移和回滚方式。

## 安全要求

- 禁止提交真实 `.codex`、会话仓库、Token、Cookie、密钥、连接串或账号数据。
- 不得降低私有仓库验证、manifest 路径验证、文件哈希或事务备份要求。
- 新增删除、覆盖、数据库写入、Git 历史重写时必须提供明确确认和测试。
- 安全漏洞请按照 [SECURITY.md](./SECURITY.md) 私下报告，不要创建公开 Issue。

## 代码风格

- 支持 Python 3.9+。
- 优先使用标准库和现有模块，避免不必要的运行时依赖。
- 用户错误应提供简洁、可执行的中文原因；完整底层输出写入受限日志。
- Windows/macOS 行为差异必须有测试或明确的手工验证说明。
