# GitHub Release Checklist

## Security

- [x] 当前 `.env` 已忽略且未被 Git 跟踪
- [x] 提供 `deploy/env.example`
- [x] 当前跟踪文件未发现高置信度真实 Key
- [ ] 由仓库所有者执行组织级 Git 历史密钥扫描与必要轮换

## Installation and Build

- [x] 隔离 Python 环境可安装运行与开发依赖
- [x] `pip check` 通过
- [x] 后端测试可从 `requirements-dev.txt` 直接执行
- [x] `pnpm install --frozen-lockfile` 成功
- [x] 前端 26 个测试通过
- [x] 前端生产构建成功

## Runtime and Core Workflow

- [x] 隔离后端健康检查成功
- [x] 前端页面可加载，Vite 代理可访问后端健康检查
- [x] CSV 上传、会话分析和三种报告生成成功
- [x] 商品销量排名严格使用“商品”维度，最高商品为 B、销量为 25
- [x] 不存在的字段返回 `INSUFFICIENT_DATA`，不编造数值
- [x] 畸形模型 JSON 转为可恢复的 ProviderError
- [x] 模拟模型回答与系统提示保留 `VERIFIED / UNVERIFIED` 机制
- [x] README 默认后端端口与前端默认代理端口一致（8001）
- [x] 无本机 Windows 绝对路径

## Repository Hygiene

- [x] 发布源码、测试、文档和依赖说明已提交
- [x] 运行数据、日志、覆盖率、Pytest 临时目录和前端缓存已忽略
- [x] 未跟踪 `.venv`、`node_modules` 或用户数据文件
- [x] 已添加 Apache License 2.0

## Final Gate

- [x] READY WITH BLOCKERS FIXED：核心发布阻断项已修复并完成隔离测试、构建和本地 API/前端联通验证。
