# GitHub Release Checklist

## Security

- [x] 当前 `.env` 已忽略且未被 Git 跟踪
- [x] 提供 `deploy/env.example`
- [x] 当前跟踪文件未发现高置信度真实 Key
- [ ] 对完整 Git 历史执行组织级密钥扫描与必要轮换

## Installation

- [x] `requirements.txt` 可在干净 Python 环境安装
- [x] `pip check` 通过
- [x] `package.json` 与锁文件可完成 `pnpm install --frozen-lockfile`
- [x] 前端生产构建成功
- [ ] 干净环境可直接执行后端测试（`pytest` 未列入开发依赖）

## Runtime

- [x] 隔离后端健康检查成功
- [x] 隔离前端可加载初始界面
- [x] 非法文件返回可理解的 422
- [x] 服务重启后分析 Session 与结果可恢复
- [ ] 畸形大模型响应可恢复，不抛出未处理异常
- [ ] 生产级结构化日志与请求关联信息完整

## Core Workflow

- [x] CSV 上传成功
- [x] 财务趋势分析成功
- [x] 三种报告可以下载
- [x] 16 项财务趋势数值独立复核正确
- [ ] 商品销量排名能严格回答请求的“商品”维度
- [ ] 干净前端与干净后端按 README 默认端口完成一次完整 UI 上传/分析

## Data Integrity

- [x] 不存在的字段返回 `INSUFFICIENT_DATA`，不编造数值
- [x] 两个并发任务不串 Dataset 或结果
- [x] 24,000 行 CSV 分析不崩溃
- [ ] 通用字段/维度语义映射有针对性 API 回归覆盖

## Documentation

- [x] 已提交 README 包含基础安装与启动步骤
- [ ] 当前待发布 README 与当前前端默认 API 端口一致
- [ ] 模型配置、测试依赖与测试命令在最终提交版本完整说明
- [x] 已知分析边界已说明

## Repository

- [ ] 发布内容已全部提交，干净克隆与已验证工作区一致
- [ ] 无本机绝对路径
- [ ] 无临时运行产物、覆盖率文件或运行日志被暂存
- [x] 未跟踪 `.venv` 与 `node_modules`
- [x] 未发现跟踪的用户数据文件
- [ ] 已添加适用 License（如作为开源仓库发布）

## Final Gate

- [ ] READY
- [x] NOT READY：存在发布内容不一致、错误的字段维度回答、畸形模型响应崩溃、端口说明不一致和绝对本机路径。
