"""Explicit, inspectable application skills. Navigation is proposed, never executed here."""
from __future__ import annotations
import importlib.util
import json
import re
import threading
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlsplit
from . import APP_VERSION
from .config import DATA_DIR, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .storage import atomic_write_text
from .document_exports import sanitize_export_text

SKILLS = [
    {"id":"product.help","name":"使用帮助","description":"解释功能和操作步骤，提供对应入口。","scope":"global","execution":"local","requires_source":False},
    {"id":"product.status","name":"工作环境","description":"读取本机版本、转写组件与任务状态。","scope":"global","execution":"local","requires_source":False},
    {"id":"library.search","name":"搜索资料","description":"在本地资料与视频证据中查找关键词。","scope":"library","execution":"local","requires_source":False},
    {"id":"note.qa","name":"内容问答","description":"围绕选中的笔记或资料回答问题。","scope":"source","execution":"configured_model_or_extract","requires_source":True},
    {"id":"note.summary","name":"总结内容","description":"归纳当前来源的重点并保留出处。","scope":"source","execution":"configured_model_or_extract","requires_source":True},
    {"id":"study.quiz","name":"自测练习","description":"根据当前来源生成可核对的自测问题。","scope":"source","execution":"configured_model_or_extract","requires_source":True},
    {"id":"general.chat","name":"通用问答","description":"调用已配置的文字模型；不自动读取笔记库。","scope":"conversation","execution":"configured_model","requires_source":False},
]
BY_ID={skill["id"]:skill for skill in SKILLS}
_lock=threading.RLock()

def resolve_skill(question: str, requested: str, has_source: bool, previous_skill: str = "") -> dict:
    if requested != "auto":
        if requested not in BY_ID: raise ValueError("unknown_skill")
        chosen=requested
        reason="用户选择"
    else:
        q=question.lower()
        if re.search(r"检查环境|当前环境|运行状态|多少任务|当前版本|队列状态",q): chosen="product.status"
        elif re.search(r"界面|弹窗|关闭|工作台|主题|夜间|深色|字号|字体|外观|按钮|打不开|找不到|报错|卡住|没反应|连接不上|删除|清理|导出|导入|怎么用|如何使用|怎么操作|如何操作|在哪里|在哪[里儿]?|设置|配置|软件|客户端|功能|skill|怎么导出|如何导出|怎么导入|怎么删除|如何清理|返回|登录|账号",q): chosen="product.help"
        elif re.search(r"检查环境|当前环境|运行状态|多少任务|当前版本|队列状态",q): chosen="product.status"
        elif re.search(r"搜索资料|搜索笔记|资料库搜索|查找资料",q): chosen="library.search"
        elif previous_skill in BY_ID and re.fullmatch(r"(那|然后|接下来|下一步|继续|为什么|怎么弄|怎么做|再详细一点|说详细点)[呢啊吗？?！!。 .]*",q.strip()): chosen=previous_skill
        elif has_source and re.search(r"总结|概括|摘要",q): chosen="note.summary"
        elif has_source and re.search(r"自测|测验|出题|考考",q): chosen="study.quiz"
        elif has_source: chosen="note.qa"
        else: chosen="general.chat"
        reason="根据问题和可用上下文自动选择"
    skill=BY_ID[chosen]
    return {"skill":skill,"reason":reason,"needs_source":skill["requires_source"] and not has_source,"reads_notes":skill["scope"] in {"source","library"},"automatic_actions":False}

def history() -> list[dict]:
    path=DATA_DIR/"assistant-history.json"
    with _lock:
        if not path.is_file():return []
        value=json.loads(path.read_text(encoding="utf-8"))
        return value.get("turns",[])[-80:]

def record_turn(question: str, result: dict) -> dict:
    item={"id":uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),"question":sanitize_export_text(question[:1000]),"answer":sanitize_export_text(result.get("answer","")[:24000]),"skill":result["skill"],"source":result.get("source","local"),"actions":result.get("actions",[]),"citations":result.get("citations",[]),"execution":result.get("execution",{})}
    with _lock:
        items=history()+[item]
        atomic_write_text(DATA_DIR/"assistant-history.json",json.dumps({"schema_version":1,"turns":items[-80:]},ensure_ascii=False))
    return item

def clear_history():
    with _lock:
        atomic_write_text(DATA_DIR/"assistant-history.json",'{"schema_version":1,"turns":[]}')

GUIDES=[
    (r"主题|夜间|深色|字号|字体|外观|动效", "阅读与外观", "侧栏的主题按钮可以切换深浅主题；设置 → 阅读与外观可调整字号、密度和完成通知。动效跟随系统的减少动态效果设置。", "settings_appearance"),
    (r"风格|模板|格式|深度|生成偏好", "生成偏好", "在设置 → 笔记与模板中选择默认风格、格式和额外要求；创建任务时也可以为本次内容单独调整。修改设置只影响后续任务，不会覆盖已生成的笔记。", "settings_notes"),
    (r"报错|失败|卡住|没反应|连接不上|打不开|error|timeout", "检查处理问题", "先查看当前任务的状态和错误提示，再检查来源是否可访问、模型连接和转写组件。不要反复提交相同任务；已有媒体可以恢复处理。打开处理记录可查看诊断或导出脱敏支持包。", "diagnostics"),
    (r"模型|key|密钥|供应商", "配置文字模型", "打开设置 → AI 模型，选择供应商并填写模型与 Key。可以先发现模型，再测试连接，最后保存模型连接。桌面端可把 Key 存在系统凭据库；不需要注册 LearnNote 账号。", "settings_model"),
    (r"转写|字幕.*没有|没有字幕|whisper|语音", "字幕与转写", "有平台或内嵌字幕时优先复用字幕。没有字幕时，在设置 → 字幕与转写选择本地 Whisper 或兼容的远程转写。组件可用不代表模型权重已下载；远程转写复用当前服务地址与 Key，需要服务支持音频接口。", "settings_transcriber"),
    (r"导出|保存.*(?:word|pdf|markdown)", "导出笔记", "先打开一份笔记并保存修改，再点击顶部导出。Markdown、Word、PDF 使用保存的个人修订稿，可以附上个人补充；原始生成稿和来源文件在导出面板中单独列出。", "export"),
    (r"删除|清理|磁盘|空间|备份|恢复|存储", "数据管理", "在设置 → 存储与连接打开存储管理。清理必须先预览，再由你确认。索引备份只包含任务索引；需要完整备份时，应备份整个数据目录。助理不会替你删除、恢复或迁移文件。", "storage"),
    (r"课程|批量|分p|播放列表", "组织课程", "点击侧栏课程，新建分组并选择已有笔记或粘贴链接。保存后可以排序、暂停和提交待处理链接。删除课程分组会保留原始笔记与资料。", "courses"),
    (r"复习|闪卡|测验|自测", "复习与自测", "打开内容后，在学习工具中创建复习卡，先核对并编辑问题和答案再加入复习库。侧栏复习用于评分；设置 → 存储与连接中的复习计划可调整目标与时区。", "review"),
    (r"导入|创建|新建|添加|视频链接|本地视频", "创建笔记", "点击新建笔记，选择视频链接、本地文件或浏览器当前页。生成前可调整风格、格式、深度、画面理解和 OCR。文档导入保留原文；视频通过字幕或转写进入整理流程。", "create"),
    (r"插件|扩展|浏览器|连接", "浏览器交接", "保持桌面客户端运行，在浏览器的视频页面打开 LearnNote 扩展，确认当前视频后发送。扩展按用户操作收集可访问的资源，不录制标签页或绕过登录权限。可从新建笔记 → 当前网页连接扩展。", "browser"),
    (r"图文|ocr|画面|片段", "视频与画面工具", "打开视频笔记后，在学习工具中选择片段学习或 OCR。片段以本地视频的起止秒数创建新笔记；OCR 展示原帧、文字和置信度，识别结果需要核对。", "tools"),
    (r"登录|账号|账户|联网|隐私", "本地使用", "LearnNote 不要求登录官方账号。资料、笔记和学习记录保存在本机。下载内容会访问来源网站；使用远程模型时，处理所需内容会发送给你配置的服务商。", "settings_storage"),
    (r"返回|关闭|退出", "返回与关闭", "窗口支持返回按钮、右上角关闭、Esc 和点击窗口外的遮罩。尚未保存的重要编辑会先提醒；助手的功能按钮只打开相应界面，不会自动执行删除等操作。", "home"),
]

def execute_global(skill_id: str, question: str, options=None, *, emit=None, control=None) -> dict:
    if skill_id not in BY_ID or BY_ID[skill_id]["requires_source"]:raise ValueError("source_skill_requires_existing_endpoint")
    result={"skill":BY_ID[skill_id],"source":"local","actions":[],"citations":[],"execution":{"state":"completed","automatic_actions":False}}
    if skill_id=="product.help":
        matches=[entry for entry in GUIDES if re.search(entry[0],question,re.I)][:2]
        if not matches and re.fullmatch(r"(那|然后|接下来|下一步|继续|为什么|怎么弄|怎么做|再详细一点|说详细点)[呢啊吗？?！!。 .]*",question.strip()):
            previous=next((t for t in reversed(history()) if t.get("skill",{}).get("id")=="product.help"),None)
            if previous:matches=[entry for entry in GUIDES if re.search(entry[0],previous["question"],re.I)][:2]
        if matches:
            result["answer"]="\n\n".join(f"### {title}\n{text}" for _,title,text,_ in matches)
            result["actions"]=[{"id":action,"label":"打开"+title} for _,title,_,action in matches]
        else:
            result["answer"]="我可以帮助你使用 LearnNote，也可以在你选择来源后总结、解释和自测。\n\n工作台功能包括：内容导入、字幕与画面、OCR、片段学习、课程与批量链接、复习、修订稿导出、索引备份和诊断。\n\n可用 Skills：\n"+"\n".join(f"- **{s['name']}**：{s['description']}" for s in SKILLS)+"\n\n你可以直接问“怎么配置模型”“如何导出 Word”，或从上方选择一个 Skill。无需登录 LearnNote。"
            result["actions"]=[{"id":"create","label":"新建笔记"},{"id":"settings_model","label":"配置模型"}]
    elif skill_id=="product.status":
        from .storage import list_tasks
        tasks=list_tasks();running=sum(t.status in {"queued","running","cancelling"} for t in tasks)
        asr=importlib.util.find_spec("faster_whisper") is not None
        result["answer"]=f"当前版本：{APP_VERSION}\n\n任务记录：{len(tasks)} 个；排队或处理中：{running} 个。\n\n本地转写组件：{'可用' if asr else '尚未安装'}。模型权重是否已下载需要另行检查。\n\n本次只读取本机状态，没有调用远程模型。"
        result["actions"]=[{"id":"settings_transcriber","label":"检查转写设置"}]
    elif skill_id=="library.search":
        from .knowledge import search_evidence
        query=re.sub(r"^(请|帮我)?\s*(搜索资料|搜索笔记|资料库搜索|查找资料)[:：\s]*","",question).strip()
        matches=search_evidence(query,6,"lexical")
        result["answer"]=("本地资料中的匹配原文：\n\n"+"\n\n".join(f"**{item.get('title','来源')}** · {item.get('locator','')}\n{str(item.get('text',''))[:900]}" for item in matches)) if matches else "没有找到匹配原文。请换成更具体的关键词，例如“学习率”。"
        result["citations"]=[{"label":item.get("title","出处"),"text":str(item.get("text",""))[:1200],"evidence_id":item["evidence_id"]} for item in matches]
    else:
        base=getattr(options,"llm_base_url",None) or LLM_BASE_URL
        parsed=urlsplit(base)
        if parsed.scheme not in {"http","https"}:raise ValueError("invalid_model_endpoint")
        from .model_connections import connected_api_key
        explicit_key=getattr(options,"llm_api_key",None) or connected_api_key(options)
        if parsed.hostname in {"localhost","127.0.0.1","::1"}:
            key=explicit_key or "local-no-key"
        else:
            key=explicit_key or (LLM_API_KEY if not getattr(options,"use_saved_connection",False) and base.rstrip("/")==LLM_BASE_URL.rstrip("/") else "")
        if not key:
            result["answer"]="通用问答需要配置文字模型。使用帮助、工作环境和资料搜索可以直接在本机使用。"
            result["actions"]=[{"id":"settings_model","label":"配置文字模型"}]
            result["execution"]["state"]="needs_configuration"
        else:
            from openai import OpenAI
            model=getattr(options,"llm_model",None) or LLM_MODEL
            base=getattr(options,"llm_base_url",None) or LLM_BASE_URL
            previous=[t for t in history() if t.get("skill",{}).get("id") in {"general.chat","product.help"}][-4:]
            messages=[{"role":"system","content":"你是 LearnNote 的全局助手。当前是通用问答，没有读取用户笔记或文件，也没有浏览网页或执行操作的工具。不要声称已经执行、下载、删除或修改。涉及软件操作时，只根据下面的功能说明回答，未列出的能力不要编造；可以建议使用帮助 Skill 打开操作入口。\n软件功能：\n" + "\n".join(title+"："+text for _,title,text,_ in GUIDES)}]
            for turn in previous:
                messages.extend([{"role":"user","content":turn["question"]},{"role":"assistant","content":turn["answer"][:4000]}])
            messages.append({"role":"user","content":sanitize_export_text(question)})
            try:
                from .assistant_stream import completion_text
                from .summarizer import chat_completion_provider_kwargs
                with OpenAI(api_key=key,base_url=base,timeout=30,max_retries=0) as client:
                    answer=completion_text(client,model=model,messages=messages,emit=emit,control=control,**chat_completion_provider_kwargs(base))
                result["answer"]=answer or "模型没有返回回答。"
                result["source"]="llm"
            except Exception:
                if emit is not None:
                    raise
                result["answer"]="当前文字模型连接失败。可以在设置中测试连接；本地使用帮助和资料搜索仍可用。"
                result["execution"]["state"]="failed"
                result["actions"]=[{"id":"settings_model","label":"检查模型连接"}]
    if control is not None:
        control.check()
    try:
        record_turn(question,result)
    except (OSError, ValueError):
        result["warning"]="回答已生成，但全局对话历史未能保存。原历史文件未被覆盖。"
    return result
