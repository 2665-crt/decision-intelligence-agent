# 数据分析决策工作台

一个本地运行的通用分析工作台：先上传 XLSX、XLS、CSV 或 DOCX 形成 Dataset，再从同一数据集创建多个独立的 Analysis Session。每个 Session 独立保存对话、结果、图表、Notebook、报告和生成文件。

## 工作方式

1. 点击“新建分析”，上传新数据集或选择已有数据集。
2. 输入本次分析需求，创建独立 Session；一个 Dataset 可以对应趋势、异常、预测等多个任务。
3. 在左栏恢复历史任务，在中间任务标签间切换，在右栏查看“结果 / 图表 / 数据 / Notebook / 报告 / 文件”。
4. 拖动两条分隔线可调整三栏宽度；宽度会保存在浏览器本地。右栏支持全屏。

切换已完成的 Session 只读取保存的状态和工件，不会重新运行分析；仅在该 Session 点击“开始分析”时才生成结果。

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
