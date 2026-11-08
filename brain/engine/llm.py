# -*- coding: utf-8 -*-
"""模型调用层（v10）。

两条通道，职责分开，互不 fallback（这点和旧版不同）：
  · `ark_chat()`  —— 出话。方舟 doubao-seed-character，**只在出话链路用**。
  · `oai_chat()`  —— 分析。本地 Ollama 或云端 OpenAI 兼容端点（Qwen 等），
                     用于画像/简报。协议不同，所以必须是两个函数，
                     不能"换个 URL 就调用"（旧版踩过：Ollama 走 /api/chat + options，
                     改 OpenAI 兼容端点直接 400）。

🔴 密钥只有一处：`BASE/.ark_key`（或环境变量 SOUL_ARK_KEY）。绝不写进源码。
🔴 thinking 必须显式给：character 模型不传该字段默认开思考（27s / 1010 reasoning tokens），
   会直接吃掉超时预算。2026-10-18 实测：只给 enabled 不给 reasoning_effort 等于没开。
"""
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request

try:
    from core.log import get_logger
    log = get_logger("brain.engine.llm")
except Exception:
    import logging
    log = logging.getLogger("engine.llm")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# BASE = E:\soul1.0


def _load_model_env():
    """读 config/model.env（与 run.py 同源）。

    为什么引擎自己要读一遍：run.py 只在 `daemon` 入口调 `_load_model_env()`，
    所以**任何不走 run.py 的脚本（自检/离线 A/B/排障）都会拿到默认模型** ——
    测试结论因此和生产不一致（2026-11-04 踩过：自检用 doubao-character 1.3s，
    生产实际是 deepseek-v4-1-flash）。这里统一兜住，两边永远是同一个模型。
    """
    p = os.path.join(BASE, "config", "model.env")
    if not os.path.isfile(p):
        return
    try:
        with io.open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_model_env()

ARK_URL = os.environ.get(
    "SOUL_ARK_URL_DIRECT",
    "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
ARK_MODEL = (os.environ.get("SOUL_ARK_MODEL_DIRECT")
             or os.environ.get("SOUL_ARK_MODEL")
             or "doubao-seed-character-260628")

# 出话超时（秒）。实测正常 6~7s，40s 是天花板（必回不能被单次调用拖死）
BRAIN_TIMEOUT = float(os.environ.get("SOUL_BRAIN_TIMEOUT", "40"))

# 本地/云端分析模型
LOCAL_URL = os.environ.get("SOUL_LOCAL_URL", "http://127.0.0.1:11434/v1/chat/completions")
LOCAL_MODEL = os.environ.get("SOUL_LOCAL_MODEL", "qwen3.5:9b-q5_K_M")
LOCAL_KEY = os.environ.get("SOUL_LOCAL_KEY", "")
LOCAL_TIMEOUT = float(os.environ.get("SOUL_LOCAL_TIMEOUT", "60"))

# 🔴 2026-11-08 21:2x（提速：一次白烧 21 秒）：
#   本地 Ollama 不可达时，**每次**调用都要吃满 Windows 的 TCP SYN 超时
#   （实测正好 21.0s，日志 `URLError(TimeoutError(10060))` 后面紧跟
#   `[简报完成] 0字 共21.0s`）。而简报是按会话触发的 → 每个新会话白等 21s。
#   这里加传输层熔断：一次失败后 10 分钟内直接返回 None，不再试。
#   要恢复实时探测就把 SOUL_LOCAL_DOWN_S 设小（如 30）。
LOCAL_DOWN_S = float(os.environ.get("SOUL_LOCAL_DOWN_S", "600") or 600)
_LOCAL_DOWN = {"until": 0.0}

# 🔴 2026-11-04 实测：Ollama 的 OpenAI 兼容端点（/v1/chat/completions）**忽略**
#    enable_thinking / thinking 两个字段 —— Qwen3.5 照样开思考，把 max_tokens 全吃在
#    reasoning 上，content 返回空、finish_reason=length（三次实测 content=0）。
#    真正的开关只有原生 /api/chat 的 `think: false`（实测 thinking=0、content 正常）。
#    ⇒ 分析调用默认走原生；要换云端 OpenAI 兼容端点时设 SOUL_ANALYZE_BACKEND=openai。
ANALYZE_BACKEND = (os.environ.get("SOUL_ANALYZE_BACKEND", "ollama") or "ollama").lower()
OLLAMA_URL = os.environ.get("SOUL_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_NUM_CTX = int(os.environ.get("SOUL_OLLAMA_CTX", "16384") or 16384)

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 直连，不走系统代理


def ark_key():
    k = (os.environ.get("SOUL_ARK_KEY") or "").strip()
    if k:
        return k
    try:
        with io.open(os.path.join(BASE, ".ark_key"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _post(url, body, key, timeout):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    t0 = time.time()
    with _OPENER.open(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw), time.time() - t0


# ────────────────────────── 出话（方舟 character）──────────────────────────
_think_lock = threading.Lock()
_think_state = {"last": 0.0}
THINK_GAP = 300.0          # 白天升档 5 分钟限一次

_REL_UP = ("加个好友", "加你", "微信", "电话", "见面", "出来", "约", "有空", "住哪", "哪儿")
_REL_RISK = ("删了", "拉黑", "不理你", "生气了", "算了", "别聊了", "没意思")
_EMO_STRONG = ("哭", "难受", "烦", "委屈", "累", "不想活", "抑郁", "崩溃", "吵架")


def thinking_for(her_msg):
    """本次请求的 thinking 配置。

    夜间（21:00~次日 6:00）用 medium —— 夜里她情绪更浓，细腻值这点延迟；
    白天默认 low；命中关系升级/风险/强情绪时升 medium（5min 限一次）。
    实测四档：disabled 1.1s / low 1.4~2.1s / medium 1.5~2.5s，都远不到必回天花板。
    """
    h = time.localtime().tm_hour
    # character 系模型必须显式 disabled（不传该字段默认开思考，27s/1010 reasoning tokens）
    if "character" in (ARK_MODEL or "").lower():
        return {"type": "disabled"}
    if h >= 21 or h < 6:
        return {"type": "enabled", "reasoning_effort": "medium"}
    t = str(her_msg or "")
    hit = ""
    for name, kws in (("关系升级", _REL_UP), ("关系风险", _REL_RISK), ("强情绪", _EMO_STRONG)):
        if t and any(k in t for k in kws):
            hit = name
            break
    if not hit:
        return {"type": "enabled", "reasoning_effort": "low"}
    with _think_lock:
        if time.time() - _think_state["last"] <= THINK_GAP:
            return {"type": "enabled", "reasoning_effort": "low"}
        _think_state["last"] = time.time()
    log.info("[思考] 白天升 medium（%s）", hit)
    return {"type": "enabled", "reasoning_effort": "medium"}


def _tcp_ok(url, timeout=0.8):
    """端口能不能连上（只判断可达性，不评估模型快慢）。"""
    try:
        import socket
        from urllib.parse import urlparse
        p = urlparse(url)
        host = p.hostname
        port = p.port or (443 if p.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def ark_chat(messages, timeout=None, her_msg="", thinking=None,
             temperature=0.9, max_tokens=2048, retries=1):
    """出话调用。成功返回文本，失败返回 None（**绝不抛** —— 必回链路最后一环）。"""
    key = ark_key()
    if not key:
        log.warning("没有 .ark_key，出话调用跳过")
        return None
    timeout = timeout or BRAIN_TIMEOUT
    think = thinking if thinking is not None else thinking_for(her_msg)
    last = None
    for attempt in range(retries + 1):
        try:
            data, dt = _post(ARK_URL, {
                "model": ARK_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "thinking": think,
            }, key, timeout)
            txt = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            u = data.get("usage") or {}
            pt = u.get("prompt_tokens") or 0
            if pt:
                cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                log.info("[ark] %.1fs 输入 %d tok · 缓存命中 %d (%.0f%%)",
                         dt, pt, cached, 100.0 * cached / pt)
            if txt.strip():
                return txt.strip()
            last = "empty content"
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                body = ""
            last = "HTTP %s %s" % (e.code, body)
            log.warning("方舟调用失败: %s", last)
            if e.code in (401, 403):        # 密钥问题，重试无用
                break
        except Exception as e:
            last = repr(e)
            log.warning("方舟调用异常: %s", last)
        if attempt < retries:
            time.sleep(0.8)
    log.warning("方舟调用最终失败: %s", last)
    return None


# ────────────────────────── 分析（OpenAI 兼容）──────────────────────────
def oai_chat(messages, timeout=None, temperature=0.3, max_tokens=1200,
             enable_thinking=False, model=None, url=None, key=None):
    """画像/简报用。失败返回 None。

    🔴 必须传 enable_thinking:false —— Qwen3.5 默认开思考会把 max_tokens 吃光、
       正文返回空（2026-10-24 与 2026-11-04 两次实测同一现象）。
    """
    url = url or LOCAL_URL
    model = model or LOCAL_MODEL
    key = LOCAL_KEY if key is None else key
    timeout = timeout or LOCAL_TIMEOUT
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if enable_thinking:
        body["enable_thinking"] = True
    else:
        body["enable_thinking"] = False
        body["thinking"] = {"type": "disabled"}
    try:
        data, dt = _post(url, body, key, timeout)
    except Exception as e:
        log.warning("分析模型调用失败(%s): %r", model, e)
        return None
    txt = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if not txt.strip():
        log.warning("分析模型返回空(%s) finish=%r", model,
                    ((data.get("choices") or [{}])[0]).get("finish_reason"))
        return None
    log.info("[local] %.1fs %s %d 字", dt, model, len(txt))
    return txt.strip()


def _fetch_image_b64(url, timeout=20):
    """下载图片转 base64（带浏览器 UA 过 Soul 防盗链）。失败返回 ("", "")。

    2026-11-04 实测：Soul 图片 URL（china-chat-img.soulapp.cn）防盗链只查 User-Agent，
    无 UA / 非浏览器 UA 一律 403；带浏览器 UA 即可 200。
    方舟服务端直接拉这个 URL 会被拒 → 必须副机先下载再以 data URI 传。
    """
    import base64
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    })
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            data = r.read()
    except Exception as e:
        log.warning("图片下载失败: %r", e)
        return "", ""
    if len(data) > 8 * 1024 * 1024:            # 8MB 保护（base64 后 ~11MB）
        log.warning("图片过大 %.1fMB，跳过识图", len(data) / 1048576.0)
        return "", ""
    u = (url or "").lower()
    if u.endswith(".png"):
        mime = "image/png"
    elif u.endswith(".webp"):
        mime = "image/webp"
    elif u.endswith(".gif"):
        mime = "image/gif"
    else:
        mime = "image/jpeg"
    return base64.b64encode(data).decode("ascii"), mime


def describe_image(image_url, timeout=25, question=""):
    """识图：返回图片的客观描述；失败返回 None（调用方回退固定话术）。"""
    if not image_url:
        return None
    try:
        b64, mime = _fetch_image_b64(image_url, timeout=min(20, timeout))
        if not b64:
            return None
        content = [
            {"type": "image_url",
             "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}},
            {"type": "text", "text": (question or
                "用一两句话客观描述这张图片：图里是什么、什么场景、有什么值得留意的细节。"
                "只描述、不评价。")},
        ]
        txt = ark_chat([{"role": "user", "content": content}], timeout=timeout,
                       thinking={"type": "disabled"})
        return (txt or "").strip() or None
    except Exception as e:
        log.warning("识图失败: %r", e)
        return None


def analyze(messages, timeout=None, temperature=0.3, max_tokens=1200, model=None):
    """分析调用统一入口：按后端选协议。失败返回 None。"""
    if ANALYZE_BACKEND == "openai":
        txt = oai_chat(messages, timeout=timeout, temperature=temperature,
                       max_tokens=max_tokens, enable_thinking=False, model=model)
    else:
        txt = ollama_chat(messages, timeout=timeout, temperature=temperature,
                          max_tokens=max_tokens, model=model)
    if txt:
        return txt
    # 🔴 2026-11-08 21:4x（用户口径「交接报告里的模型等等」）：
    #   本地 Ollama（主 PC 的 11434）在防火墙后面时副机连不上，
    #   于是「简报 / 画像 L0-L1」永远是 0 字（实测 `[简报完成] sid=... 0字 共21.0s`）。
    #   简报是**每会话一次**的后台活，prompt 1~2k token、输出 ≤260 字，
    #   用已经配好的方舟出话模型跑，成本约 0.005 元/次，延迟 1~3s，完全可接受。
    #   所以本地不可用时**自动回落到方舟**（同一把 .ark_key，不新增密钥）。
    #   关掉：SOUL_ANALYZE_FALLBACK_ARK=0
    if os.environ.get("SOUL_ANALYZE_FALLBACK_ARK", "1") == "1":
        log.info("本地分析模型不可用 → 回落到方舟 %s", ARK_MODEL)
        return ark_chat(messages, timeout=timeout or 40, temperature=temperature,
                        max_tokens=max_tokens, thinking={"type": "disabled"})
    return None


def ollama_chat(messages, timeout=None, temperature=0.3, max_tokens=1200, model=None):
    """Ollama 原生 /api/chat。**`think: False` 是唯一能真关思考的开关。**

    num_ctx 必须和常驻 runner 一致（生产 16384）：传不同的值会另起一个 runner，
    旧的 30 分钟内不释放 → 显存假满、单次耗时从 12s 涨到 35s+（实测）。
    """
    if time.time() < _LOCAL_DOWN["until"]:
        return None                      # 熔断中：本地模型不可达，别白等
    # 🔴 2026-11-08 21:4x（实测 22.2s 里 21s 全在等 TCP）：熔断只在**失败之后**生效，
    #   进程刚起来第一次调用仍要吃满 Windows 的 SYN 超时。这里先做 0.8s 的端口探测，
    #   探不通就直接判不可用 —— 正常 Ollama 探测 <10ms，代价可忽略。
    if not _tcp_ok(OLLAMA_URL):
        _LOCAL_DOWN["until"] = time.time() + LOCAL_DOWN_S
        log.warning("本地 Ollama 端口不通（%s）→ 静默 %.0f 分钟，分析走方舟",
                    OLLAMA_URL.split("//")[-1].split("/")[0], LOCAL_DOWN_S / 60.0)
        return None
    model = model or LOCAL_MODEL
    timeout = timeout or LOCAL_TIMEOUT
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    try:
        data, dt = _post(OLLAMA_URL, body, "", timeout)
    except Exception as e:
        _LOCAL_DOWN["until"] = time.time() + LOCAL_DOWN_S
        log.warning("Ollama 调用失败(%s): %r → 本地模型静默 %.0f 分钟（不阻塞回复）",
                    model, e, LOCAL_DOWN_S / 60.0)
        return None
    m = data.get("message") or {}
    txt = (m.get("content") or "").strip()
    th = len(m.get("thinking") or "")
    if not txt:
        log.warning("Ollama 返回空(%s) done=%r thinking=%d eval=%r",
                    model, data.get("done_reason"), th, data.get("eval_count"))
        return None
    log.info("[ollama] %.1fs %s %d 字 (thinking %d)", dt, model, len(txt), th)
    return txt


def analyze_available():
    """分析模型是否配置可用（无 key 也能调本地）。"""
    if os.environ.get("SOUL_ANALYZE_FALLBACK_ARK", "1") == "1" and ark_key():
        return True
    return bool((OLLAMA_URL if ANALYZE_BACKEND == "ollama" else LOCAL_URL) and LOCAL_MODEL)


__all__ = ["BASE", "ARK_URL", "ARK_MODEL", "BRAIN_TIMEOUT",
           "LOCAL_URL", "LOCAL_MODEL", "OLLAMA_URL", "ANALYZE_BACKEND", "ark_key",
           "thinking_for", "ark_chat", "oai_chat", "ollama_chat", "analyze",
           "describe_image", "analyze_available"]
