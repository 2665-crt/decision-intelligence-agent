# 数据分析决策工作台

一个本地运行的通用分析工作台：上传 XLSX、XLS、CSV 或 DOCX，输入目标后得到数据概览、质量检查、趋势图、可用时的预测、风险清单、低损害优先的方案比较，以及 Markdown、HTML、Word 报告。

## 本机启动（默认，不依赖 Docker）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn studio_api.app:app --app-dir backend --host 127.0.0.1 --port 8001
pnpm --dir apps/web install
pnpm --dir apps/web dev --host 127.0.0.1 --port 5173
```

前端会把 `/api` 转发到本地 API 的 `8001` 端口。

打开 `http://localhost:5173`。

## Docker 部署（可选）

仅在需要容器化部署时使用：

```powershell
docker compose -f deploy/docker-compose.yml up -d --build
```

## 决策边界

- 只运行固定分析函数，不执行用户或模型生成的代码。
- 预测只在用户请求预测、检测到时间列与数值列、且候选趋势模型优于朴素基线时推荐。
- DOCX 内容标为“文档陈述”，不会当成已验证数据事实。
- 医疗、法律、金融、化工与施工安全目标会标记人工复核；输出是辅助分析，不替代专业处置结论。
