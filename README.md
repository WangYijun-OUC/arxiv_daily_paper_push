# 📚 ArXiv 每日论文推送助手

自动抓取 ArXiv 最新 AI 论文，使用 DeepSeek 进行深度分析，并推送到飞书和邮箱。

## ✨ 功能特性

- 🔍 **自动抓取**：每日自动获取 ArXiv 最新 LLM / AI Agent / Deep Learning 相关论文
- 🤖 **AI 深度分析**：调用 DeepSeek API 生成结构化中文解读：
  - 【快速抓要点】核心问题与方法
  - 【逻辑推导】起承转合还原作者思路
  - 【技术细节】关键实现细节
  - 【局限性】潜在不足
  - 【专业知识解释】术语科普
- 💻 **代码链接**：自动从 PapersWithCode 匹配开源代码
- 📱 **飞书推送**：生成精美富文本卡片推送至飞书群
- 📧 **邮箱推送**：通过 SMTP 将日报同步发送到指定邮箱

## 🚀 快速开始

### 1. 环境准备

```bash
pip install arxiv requests
```

### 2.配置

- 编辑 daily_paper.py，填写以下配置项：

```python
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/你的Webhook地址"
DEEPSEEK_API_KEY = "你的DeepSeek API Key"  # 或通过环境变量 DEEPSEEK_API_KEY 设置
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"  # 可选: deepseek-chat | deepseek-reasoner | deepseek-v4-pro | deepseek-v4-flash

# 邮箱推送配置（默认关闭；填写 SMTP 信息后改为 True）
EMAIL_ENABLED = False
SMTP_HOST = "smtp.example.com"
SMTP_PORT = 465
SMTP_USERNAME = "your_email@example.com"
SMTP_PASSWORD = "your_email_password_or_app_password"
SMTP_USE_SSL = True
SMTP_USE_TLS = False
EMAIL_FROM = SMTP_USERNAME
EMAIL_TO = ["recipient@example.com"]
EMAIL_SUBJECT_PREFIX = "ArXiv 每日论文"
```

- 飞书 Webhook：在飞书群设置 → 添加机器人 → 自定义机器人 → 获取 Webhook 地址
- DeepSeek API Key：在 DeepSeek 开放平台 获取
- 邮箱 SMTP：在邮箱服务商开启 SMTP/客户端授权，填写服务器地址、端口、账号和授权码
- 如使用 465 端口，通常保持 `SMTP_USE_SSL = True`；如使用 587 端口，通常设置 `SMTP_USE_SSL = False` 且 `SMTP_USE_TLS = True`
- 支持多个收件人，例如：`EMAIL_TO = ["a@example.com", "b@example.com"]`

### 3.设置每日自动运行（Windows 任务计划程序）

1. 搜索打开「任务计划程序」
2. 点击右侧「创建基本任务」
3. 名称：ArXiv每日论文推送
4. 触发器：选择「每天」，设置运行时间（如 09:00）
5. 操作：选择「启动程序」
6. 程序或脚本：C:\Users\你的用户名\Desktop\run_arxiv.bat（或实际路径）
7. 起始于（可选）：C:\Users\你的用户名\Desktop
8. 完成：勾选「当单击"完成"时，打开此任务属性的对话框」
9. 高级设置（可选）：
   「条件」→ 取消勾选「只有在计算机使用交流电源时才启动」
   「设置」→ 勾选「如果任务失败，按以下频率重新启动」

### 4.注意事项

- 确保网络可访问 ArXiv、DeepSeek API、飞书服务器和 SMTP 服务器
- 建议先手动运行测试，确认配置无误后再设置定时任务
- 如需修改论文查询关键词，编辑 daily_paper.py 中的 query 参数
