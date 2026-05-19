import arxiv
import requests
import json
import html
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
import time

# --- 配置区 ---
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/your_webhook"
DEEPSEEK_API_KEY = "your_api_key"  
DEEPSEEK_API_URL = "your_api_url"

# 邮箱推送配置（默认关闭；填写 SMTP 信息后改为 True）
EMAIL_ENABLED = False
SMTP_HOST = "smtp.126.com"
SMTP_PORT = 465
SMTP_USERNAME = "wangyijun010522@126.com"
SMTP_PASSWORD = "ELwqV3AUZqMJjnFS"
SMTP_USE_SSL = True
SMTP_USE_TLS = False
EMAIL_FROM = SMTP_USERNAME
EMAIL_TO = ["wangyijun010522@126.com"]
EMAIL_SUBJECT_PREFIX = "ArXiv 每日论文"

PWC_BASE_URL = "https://arxiv.paperswithcode.com/api/v0/papers/"

def get_code_link(arxiv_url):
    """从 PapersWithCode 获取代码链接"""
    arxiv_id = arxiv_url.split('/')[-1].split('v')[0]
    try:
        r = requests.get(f"{PWC_BASE_URL}{arxiv_id}", timeout=10).json()
        if "official" in r and r["official"]:
            return r["official"]["url"]
    except:
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
        "model": "deepseek-chat", 
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
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        res_json = response.json()
        
        # 增加这部分调试代码
        if 'error' in res_json:
            return f"DeepSeek API 报错: {res_json['error']['message']}"
        
        if 'choices' not in res_json:
            return f"API 未预期响应: {json.dumps(res_json)}"

        return res_json['choices'][0]['message']['content']
    except Exception as e:
        return f"网络或系统错误: {str(e)}"

def push_to_feishu(report_content):
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
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "基于 DeepSeek-V3 自动生成"}]}
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
  <p><em>基于 DeepSeek-V3 自动生成</em></p>
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
            print(f"正在分析第 {i+1}/{len(results)} 篇: {res.title}")
            
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
