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
# 敏感信息：在 .env 中设置 DEEPSEEK_API_KEY / USTC_API_KEY、SMTP_PASSWORD、SMTP_USERNAME

# LLM 调用渠道: "official" 官方 DeepSeek | "ustc" 中科大校内平台
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "official")

LLM_PROVIDERS = {
    "official": {
        "name": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_api_key": "your_deepseek_api_key",
        "temperature": None,
    },
    "ustc": {
        "name": "中科大 LLM 平台",
        "base_url": "https://api.llm.ustc.edu.cn/v1",
        "api_key_env": "USTC_API_KEY",
        "api_key_fallback_env": "DEEPSEEK_API_KEY",
        "default_api_key": "your_ustc_api_key",
        "temperature": float(os.environ.get("USTC_TEMPERATURE", "0.3")),
    },
}

FEISHU_ENABLED = False
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/your_webhook"

# 各渠道支持的模型（修改 DEEPSEEK_MODEL 即可切换）
PROVIDER_MODELS = {
    "official": {
        "deepseek-chat": "通用对话，速度快，适合日常论文摘要",
        "deepseek-reasoner": "推理模型，先思考再回答，质量更高但更慢、更耗 token",
        "deepseek-v4-pro": "V4 旗舰模型，效果最好",
        "deepseek-v4-flash": "V4 快速版，速度与效果平衡",
    },
    "ustc": {
        "deepseek-v4-flash": "V4 快速版（校内平台推荐）",
        "deepseek-v4-pro": "V4 旗舰模型",
    },
}
_default_model = "deepseek-v4-flash" if LLM_PROVIDER == "ustc" else "deepseek-chat"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", _default_model)
# 仅 official + deepseek-reasoner 生效：是否在推送正文中附带思考过程（CoT）
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

def get_provider_config():
    """获取当前 LLM 渠道配置"""
    if LLM_PROVIDER not in LLM_PROVIDERS:
        supported = ", ".join(LLM_PROVIDERS.keys())
        raise ValueError(f"无效的 LLM_PROVIDER: {LLM_PROVIDER!r}，可选值: {supported}")
    return LLM_PROVIDERS[LLM_PROVIDER]

def get_provider_models():
    """获取当前渠道支持的模型列表"""
    return PROVIDER_MODELS[LLM_PROVIDER]

def get_chat_completions_url(base_url):
    """将 base_url 规范为 chat/completions 端点"""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"

def resolve_api_key(provider_cfg):
    """解析当前渠道的 API Key"""
    key = os.environ.get(provider_cfg["api_key_env"], "").strip()
    fallback_env = provider_cfg.get("api_key_fallback_env")
    if not key and fallback_env:
        key = os.environ.get(fallback_env, "").strip()
    if not key:
        key = provider_cfg.get("default_api_key", "")
    return key

def get_llm_request_settings():
    """组装 LLM 请求所需的 URL、Key、温度等参数"""
    provider_cfg = get_provider_config()
    return {
        "provider_name": provider_cfg["name"],
        "api_url": get_chat_completions_url(provider_cfg["base_url"]),
        "api_key": resolve_api_key(provider_cfg),
        "temperature": provider_cfg.get("temperature"),
    }

def validate_deepseek_model():
    """校验渠道与模型配置"""
    get_provider_config()
    models = get_provider_models()
    if DEEPSEEK_MODEL not in models:
        supported = ", ".join(models.keys())
        raise ValueError(
            f"渠道 [{LLM_PROVIDER}] 不支持模型 {DEEPSEEK_MODEL!r}，"
            f"可选值: {supported}"
        )
    settings = get_llm_request_settings()
    if settings["api_key"].startswith("your_"):
        key_hint = get_provider_config()["api_key_env"]
        raise ValueError(f"请先在 .env 中配置 {key_hint}")

def get_deepseek_timeout():
    """推理模型耗时更长，自动延长超时"""
    if LLM_PROVIDER == "official" and DEEPSEEK_MODEL == "deepseek-reasoner":
        return 300
    return 120

def get_model_footer():
    """生成推送页脚中的模型说明"""
    provider_cfg = get_provider_config()
    desc = get_provider_models().get(DEEPSEEK_MODEL, "")
    return f"基于 {provider_cfg['name']} ({DEEPSEEK_MODEL}) 自动生成 — {desc}"

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

    llm = get_llm_request_settings()
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个学术分析专家，擅长将复杂的人工智能领域的论文总结得清晰易懂。"},
            {"role": "user", "content": prompt_text}
        ],
        "stream": False,
    }
    if llm["temperature"] is not None:
        payload["temperature"] = llm["temperature"]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm['api_key']}",
    }

    api_label = llm["provider_name"]
    try:
        response = requests.post(
            llm["api_url"], headers=headers, json=payload, timeout=get_deepseek_timeout()
        )

        if not response.ok:
            body_preview = (response.text or "")[:300]
            return (
                f"{api_label} HTTP {response.status_code}: "
                f"{body_preview or '(空响应)'}"
            )

        if not response.text or not response.text.strip():
            return f"{api_label} 返回空响应，请检查 API 地址与网络连接。"

        try:
            res_json = response.json()
        except ValueError:
            body_preview = response.text[:300]
            return f"{api_label} 返回非 JSON 内容: {body_preview}"

        if "error" in res_json:
            err = res_json["error"]
            msg = err.get("message", err) if isinstance(err, dict) else err
            return f"{api_label} 报错: {msg}"

        if "choices" not in res_json or not res_json["choices"]:
            return f"API 未预期响应: {json.dumps(res_json, ensure_ascii=False)[:500]}"

        return extract_deepseek_content(res_json)
    except requests.Timeout:
        return f"{api_label} 请求超时，请稍后重试。"
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
    llm = get_llm_request_settings()
    print(
        f"LLM 渠道: {llm['provider_name']} ({LLM_PROVIDER}) | "
        f"模型: {DEEPSEEK_MODEL} — {get_provider_models()[DEEPSEEK_MODEL]}"
    )
    print(f"API 端点: {llm['api_url']}")
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
