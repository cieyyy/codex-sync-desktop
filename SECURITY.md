# Security Policy

## Supported Versions

安全修复优先进入最新 Beta 和最新稳定版本。旧测试包可能不会单独回补。

## Reporting a Vulnerability

请使用 GitHub 仓库的 **Security > Report a vulnerability** 私下报告。不要在公开 Issue、Discussion、Pull Request 或截图中包含真实会话、GitHub Token、Codex 凭据、API Key、密码、连接串或私有仓库地址。

报告建议包含：

- 受影响版本和操作系统；
- 最小化、脱敏的复现步骤；
- 预期影响和攻击前提；
- 可公开的修复建议。

## Security Boundary

- 软件源码可以公开，但用户同步仓库必须保持私有。
- 导出器不上传 `auth.json`、原始 Codex SQLite、图片和附件目录。
- 会话正文中的敏感文字会被保留，软件不是秘密脱敏器。
- GitHub 登录由 GitHub CLI、默认浏览器和系统凭据存储处理。
- 文件导入前验证安全相对路径和 SHA-256，写库前创建事务撤销点。
- 安装包尚无商业代码签名或 Apple 公证，用户应核对 Release 校验和。
