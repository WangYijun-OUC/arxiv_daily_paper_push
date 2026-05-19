import arxiv
import os
import requests
import json
import html
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
import time

def _load_dotenv():
    """从项目目录 .env 加载环境变量（文件已加入 .gitignore，不会上传）"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

_load_dotenv()

# --- 配置区 ---
# 敏感信息：在 .env 或系统环境变量中设置 DEEPSEEK_API_KEY、SMTP_PASSWORD、SMTP_USERNAME
FEISHU_ENABLED = False
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/your_webhook"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "your_deepseek_api_key")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# DeepSeek 模型选择（修改 DEEPSEEK_MODEL 即可切换）
DEEPSEEK_MODELS = {
    "deepseek-chat": "通用对话，速度快，适合日常论文摘要",
    "deepseek-reasoner": "推理模型，先思考再回答，质量更高但更慢、更耗 token",
    "deepseek-v4-pro": "V4 旗舰模型，效果最好",
    "deepseek-v4-flash": "V4 快速版，速度与效果平衡",
}
DEEPSEEK_MODEL = "deepseek-chat"
# 仅 deepseek-reasoner 生效：是否在推送正文中附带模型的思考过程（CoT）
DEEPSEEK_INCLUDE_REASONING = False

# 邮箱推送配置（默认关闭；填写 SMTP 信息后改为 True）
EMAIL_ENABLED = True
SMTP_HOST = "smtp.126.com"
SMTP_PORT = 465
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "your_email@example.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "your_smtp_password")
SMTP_USE_SSL = True
SMTP_USE_TLS = False
EMAIL_FROM = SMTP_USERNAME
EMAIL_TO = ["wangyijun010522@126.com"]
EMAIL_SUBJECT_PREFIX = "ArXiv 每日论文"

PWC_BASE_URL = "https://arxiv.paperswithcode.com/api/v0/papers/"

def validate_deepseek_model():
    """校验配置的模型是否在支持列表中"""
    if DEEPSEEK_MODEL not in DEEPSEEK_MODELS:
        supported = ", ".join(DEEPSEEK_MODELS.keys())
        raise ValueError(
            f"无效的 DEEPSEEK_MODEL: {DEEPSEEK_MODEL!r}，"
            f"可选值: {supported}"
        )

def get_deepseek_timeout():
    """推理模型耗时更长，自动延长超时"""
    if DEEPSEEK_MODEL == "deepseek-reasoner":
        return 300
    return 120

def get_model_footer():
    """生成推送页脚中的模型说明"""
    desc = DEEPSEEK_MODELS.get(DEEPSEEK_MODEL, "")
    return f"基于 DeepSeek ({DEEPSEEK_MODEL}) 自动生成 — {desc}"

def extract_deepseek_content(res_json):
    """从 API 响应中提取正文，兼容 reasoner 的 reasoning_content"""
    message = res_json["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    reasoning = (message.get("reasoning_content") or "").strip()

    if reasoning and DEEPSEEK_INCLUDE_REASONING:
        parts = [f"【思考过程】\n{reasoning}"]
        if content:
            parts.append(f"【分析结果】\n{content}")
        return "\n\n".join(parts)

    return content or "（模型未返回内容）"

def get_code_link(arxiv_url):
    """从 PapersWithCode 获取代码链接"""
    arxiv_id = arxiv_url.split('/')[-1].split('v')[0]
    try:
        r = requests.get(f"{PWC_BASE_URL}{arxiv_id}", timeout=10)
        if not r.ok or not r.text.strip():
            return None
        data = r.json()
        if "official" in data and data["official"]:
            return data["official"]["url"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None

def summarize_with_deepseek(paper):
    """使用 DeepSeek 进行论文摘要深度总结"""
    # 构造 Prompt
    prompt_text = f"""你是一个学术分析专家。请根据以下论文的标题和摘要提供中文深度分析。
    论文标题: {paper['title']}
    论文摘要: {paper['summary']}
    
    请严格按此格式输出：
    【快速抓要点】: （简练的语言说明该研究解决了什么问题？提出了什么新的方法？得出了什么结果结论？）
    【逻辑推导】：  (不要堆砌技术细节，而是还原作者的思考路径，请按“起承转合”的结构讲解：**背景（context）**：为什么大家之前解决不好这个问题？**破局（insight）**：作者是怎么灵光一现的？他的核心直觉是什么？怎么把问题拆解为更具体的子问题的？**拆解**：这个方法具体分几步实现？用1，2，3列表简洁描述输入到输出的过程。）
    【技术细节】: （补充论文中最关键的1-2个技术实现细节（比如某个特殊的Loss Function或数据处理技巧）
    【局限性】: （潜在不足）
    【专业知识解释】: （解释论文中核心实验方法涉及的专业名词概念（比如SFT微调、ResNet架构、推理等）
    """

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个学术分析专家，擅长将复杂的人工智能领域的论文总结得清晰易懂。"},
            {"role": "user", "content": prompt_text}
        ],
        "stream": False
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

      
    try:
        response = requests.post(
            DEEPSEEK_API_URL, headers=headers, json=payload, timeout=get_deepseek_timeout()
        )

        if not response.ok:
            body_preview = (response.text or "")[:300]
            return (
                f"DeepSeek API HTTP {response.status_code}: "
                f"{body_preview or '(空响应)'}"
            )

        if not response.text or not response.text.strip():
            return "DeepSeek API 返回空响应，请检查 API URL 与网络连接。"

        try:
            res_json = response.json()
        except ValueError:
            body_preview = response.text[:300]
            return f"DeepSeek API 返回非 JSON 内容: {body_preview}"

        if "error" in res_json:
            err = res_json["error"]
            msg = err.get("message", err) if isinstance(err, dict) else err
            return f"DeepSeek API 报错: {msg}"

        if "choices" not in res_json or not res_json["choices"]:
            return f"API 未预期响应: {json.dumps(res_json, ensure_ascii=False)[:500]}"

        return extract_deepseek_content(res_json)
    except requests.Timeout:
        return "DeepSeek API 请求超时，请稍后重试。"
    except requests.RequestException as e:
        return f"网络请求失败: {e}"

def push_to_feishu(report_content):
    if not FEISHU_ENABLED:
        return
    """发送飞书富文本卡片"""
    header = { "Content-Type": "application/json" }
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": { "tag": "plain_text", "content": f"🚀 ArXiv {datetime.now().strftime('%m-%d')}" },
                "template": "orange" 
            },
            "elements": [
                {"tag": "markdown", "content": report_content},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": get_model_footer()}]}
            ]
        }
    }
    requests.post(FEISHU_WEBHOOK, headers=header, json=payload)

def markdown_links_to_html(text):
    """将报告中的 Markdown 链接转换为邮件 HTML 链接"""
    escaped_text = html.escape(text)
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2">\1</a>',
        escaped_text
    )

def build_email_html(report_content):
    """构建适合邮箱阅读的 HTML 内容"""
    html_lines = []
    for raw_line in report_content.splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue

        line = markdown_links_to_html(stripped_line)
        if stripped_line.startswith("### "):
            html_lines.append(f"<h2>{line[4:]}</h2>")
        elif stripped_line == "---":
            html_lines.append("<hr>")
        else:
            html_lines.append(f"<p>{line}</p>")

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; line-height: 1.6; color: #222; }}
    h1, h2 {{ color: #d46b08; }}
    a {{ color: #1677ff; }}
    hr {{ border: none; border-top: 1px solid #eee; margin: 24px 0; }}
  </style>
</head>
<body>
  <h1>ArXiv {datetime.now().strftime('%Y-%m-%d')}</h1>
  {''.join(html_lines)}
  <p><em>{html.escape(get_model_footer())}</em></p>
</body>
</html>"""

def push_to_email(report_content):
    """发送邮件推送"""
    if not EMAIL_ENABLED:
        return

    recipients = EMAIL_TO if isinstance(EMAIL_TO, (list, tuple)) else [EMAIL_TO]
    recipients = [recipient.strip() for recipient in recipients if recipient and recipient.strip()]
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD or not recipients:
        raise ValueError("邮箱推送配置不完整，请检查 SMTP_HOST、SMTP_USERNAME、SMTP_PASSWORD 和 EMAIL_TO。")

    message = EmailMessage()
    message["Subject"] = f"{EMAIL_SUBJECT_PREFIX} {datetime.now().strftime('%Y-%m-%d')}"
    message["From"] = EMAIL_FROM or SMTP_USERNAME
    message["To"] = ", ".join(recipients)
    message.set_content(report_content, subtype="plain", charset="utf-8")
    message.add_alternative(build_email_html(report_content), subtype="html")

    context = ssl.create_default_context()
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls(context=context)
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)

if __name__ == "__main__":
    validate_deepseek_model()
    print(f"使用 DeepSeek 模型: {DEEPSEEK_MODEL} — {DEEPSEEK_MODELS[DEEPSEEK_MODEL]}")
    print("正在搜集最新论文...")
    client = arxiv.Client()
    search = arxiv.Search(
        query="abs:LLM OR abs:\"AI Agent\" OR abs:\"Deep Learning\"", 
        max_results=3, 
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    
    full_report = ""
    results = list(client.results(search))
    
    if not results:
        print("今日暂无新论文。")
    else:
        for i, res in enumerate(results):
            print(f"正在分析第 {i+1}/{len(results)} 篇 ({DEEPSEEK_MODEL}): {res.title}")
            
            code_url = get_code_link(res.entry_id)
            code_md = f" | [💻 代码]({code_url})" if code_url else ""
            
            paper_info = {
                "title": res.title,
                "summary": res.summary.replace('\n', ' '),
                "url": res.entry_id
            }
            
            summary = summarize_with_deepseek(paper_info)
            full_report += f"### {i+1}. {res.title}\n🔗 [原文]({res.entry_id}){code_md}\n{summary}\n\n---\n"
        
        push_to_feishu(full_report)
        push_to_email(full_report)
        print("推送完成！")
