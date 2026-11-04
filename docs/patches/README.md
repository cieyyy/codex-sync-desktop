# 构建工作流补丁

`build-workflow.patch` 保存本机 `.github/workflows/build.yml` 的构建修正：安装完整项目依赖、加入 PNG 图标资源、签名 macOS 应用。

本次 GitHub 登录授权不含 workflow scope，无法直接更新工作流文件，因此将完整改动保存为补丁，活动工作流保持仓库版本。取得相应授权后可在仓库根目录执行：

```sh
git apply --ignore-space-change docs/patches/build-workflow.patch
```
