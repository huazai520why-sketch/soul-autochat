# 架构详解

> 本文写给要改代码的人。只想跑起来看 [README](README.md)。
> 每一节末尾的「为什么」比「是什么」重要——那些都是真实故障换来的。
> 2026-11-14 当前任务拓扑与包依赖总图见 [PROJECT_MAP.md](PROJECT_MAP.md)。

---

## 目录

1. [设计前提：为什么难](#1-设计前提为什么难)
2. [分层与依赖规则](#2-分层与依赖规则)
3. [感知层：一次读屏发生了什么](#3-感知层一次读屏发生了什么)
4. [动作层：一次点击发生了什么](#4-动作层一次点击发生了什么)
5. [决策层：一条消息怎么被回掉](#5-决策层一条消息怎么被回掉)
6. [生成层：一句话怎么被造出来](#6-生成层一句话怎么被造出来)
7. [主循环：一轮里都干了什么](#7-主循环一轮里都干了什么)
8. [数据层：为什么直读数据库](#8-数据层为什么直读数据库)
9. [并发生命周期：锁、心跳、自愈](#9-并发生命周期锁心跳自愈)
10. [关键常量总表](#10-关键常量总表)
11. [已知坑与设计取舍](#11-已知坑与设计取舍)

---

## 1. 设计前提：为什么难

普通爬虫面对的是稳定的 HTTP 接口；本项目面对的是一个**随时会变的 GUI**：

| 现实 | 后果 | 本项目的应对 |
|---|---|---|
| dump 一棵 UI 树要 2~4s | 一轮十几次判断 = 分钟级 | 帧复用（`FRAME_TTL`）+ 动作代数 |
| 页面转场期间 dump 到的是「半张图」 | 判定忽真忽假 | 判据用**结构**（resource-id）不是文案；允许 `unknown` 并重试 |
| 控件文案随版本改 | 硬编码文案必死 | 优先 res-id，文案只做兜底且要求命中 ≥2 条 |
| 点击可能丢（模拟器卡顿） | 「点了没反应」 | 点后校验 + 新帧重新定位 + 只重试一次 |
| 弹窗可能是自绘的 | UI 树里没有节点 | 承认这个现实：少数场景只能 OCR |
| App 会卡在网页页 / 容器页 | 所有按钮都点不到 | 用 `am start --activity-clear-top` 强制回主界面 |
| 设备会挂死 | 整个机器人停摆 | 三级自愈（adb 重连 → root+u2 → 重建模拟器） |

**核心思想：永远不要假设「刚才那一下成功了」。** 每个动作后都要有确认，每个判定都要有兜底。

---

## 2. 分层与依赖规则

```
guard/  ──依赖──▶ brain/ ──依赖──▶ eyes/ + hands/ ──依赖──▶ core/
                                        │
                                        └──▶ data/
```

**硬规则（违反会导致不可测）**：

1. `eyes/` **不许** import `hands/`——感知层永远不能产生副作用。
2. `hands/` **不许** import `eyes/`——动作层永远不做判断。
3. `brain/` 不许直接调 `u2`——必须走 `Actor`，否则帧缓存会脏。
4. 所有「谁该回」的判断只能来自 `pendingq.candidates()`。

**当前依赖状态**：跨层违规已清零。冷却/已回台账位于 `data/pending_ledger.py`，
消息分类位于 `core/message_kind.py`，`run.py match` 的运行逻辑位于
`brain/match_runner.py`。brain 内部仍有少量历史环，修改这些区域时要先跑回放。

第 3 条的由来：早期为了图快，在几个地方直接 `u2(...)` 点了屏幕，
`Actor` 的缓存帧不知道页面已经变了，后续所有基于旧帧的坐标全部错位。

---

## 3. 感知层：一次读屏发生了什么

### 3.1 UI 树通道

```python
# eyes/uitree.py
def get(...):                     # 带超时兜底的 dump
    ...
def parse(xml) -> Snapshot        # ET.fromstring + 递归 walk
class Snapshot:
    def find(text=, desc=, res=)  # 精确查找
    def hit(...)                  # 三级定位（见下）
    def tab(name)                 # 底栏 tab，优先 res-id
    def signature()               # 页面指纹，用来判断"还是同一页吗"
```

**关键：`dump` 必须放在线程里 join(timeout)**。
`uiautomator2` 的 `dump_hierarchy` 没有超时参数，设备卡一下就是永久阻塞。
`DUMP_TIMEOUT=20` 秒兜住，超时当失败处理，不要当异常抛出——上层要能继续。

### 3.2 三级控件定位 `Snapshot.hit()`

```
① 自身 clickable        → 直接用
② 上溯祖先找 clickable   → 用祖先的 bounds
③ 几何反查              → 找所有 clickable 节点中，包含目标中心点、且面积最小的那个
```

第 ③ 级不是可选项。底栏「聊天」的文字是 `TextView`，它和可点的 `View` 是**兄弟节点**，
没有任何祖先关系，只能靠坐标包含关系反查。

### 3.3 页面识别 `eyes/page.py::detect()`

返回值只有 7 种：`chatlist / chat / greeting / square / me / planet / unknown`。

判据顺序（**结构优先**）：

```
1. 「收到的新招呼」+ 详情页特征文本 → greeting
2. res-id = et_sendmessage / sendmessage → chat
3. 「发送」且没有底栏 → chat
4. res-id = currentOnlineNumTv → planet        ← 星球页独有，不受改版影响
5. 特征文本命中 ≥2 条 → 对应的页
6. 有列表容器且行数 ≥2 → chatlist
7. 否则 → unknown
```

**为什么 `unknown` 是合法的返回值**：页面转场时确实无法判断。
上层必须能处理 `unknown`（重试 / 导航 / 等待），而不是假设它不存在。

### 3.4 会话列表解析（`eyes/chatlist.py`）

三层下钻，每层都在排除误判：

```
list_view()  → 高度 > 50% 屏高 + 子节点 ≥2（优先 res-id = conversation_list）
_descend_to_rows() → 不断往下钻，直到某一层子节点 ≥2
rows()       → 双闸：行高 ≥ 6.9% 屏高 + 行内有内容
```

`ROW_MIN_H_RATIO=0.069` 是实测值：正常会话行 135~153px（占屏 8.4%~9.6%），
非行干扰项（Soul 通知横幅 48px、底部残行 95px、末梢 7px）都落在阈值下方。

### 3.5 OCR 通道（只在必要处）

用 `eyes/chat.py` 判断气泡归属：

| 常量 | 值 | 含义 |
|---|---|---|
| `MSG_TOP` | 140 | 状态栏/标题栏以下 |
| `MSG_BOTTOM` | 1400 | 快捷栏以上 |
| `RIGHT_EDGE` | 700 | 气泡右边界 ≥ 此值 → 我发的 |
| `LEFT_EDGE` | 210 | 气泡左边界 ≤ 此值 → 对方发的 |

**只用于**：慢路径兜底、发图后确认、奇遇铃（自绘弹窗，树里无节点）。
正常链路一律走 UI 树，不跑 OCR。

---

## 4. 动作层：一次点击发生了什么

### 4.1 统一入口 `hands/tap.py`

```python
def _do(dev, method, *args):
    dev.note_action()          # ← 先让所有缓存帧失效
    try: getattr(dev.u2(), method)(*args)
    except ...: retry once with a fresh connection
```

**顺序不能颠倒**：先作废缓存，再动手。反过来的话，
「动作已经开始但缓存还有效」的窗口里，任何读取都会拿到旧帧。

### 4.2 动作后确认 `brain/act.py`

```python
FRAME_TTL = 1.2
def tap_node(node, settle=..., force=False):
    ...snap...        # 可能命中缓存
    _after(force=True)  # ← 动作后永远强制重取，不复用
```

`force=True` 是硬规则：**动作之后的第一帧永不复用**。

### 4.3 发送三态（防重复的关键）

```python
sent_ok(...) -> "ok" | "unknown" | "residual"
```

| 状态 | 依据 | 记账 |
|---|---|---|
| `ok` | 输入框已空 | 记为已发 |
| `unknown` | 读不到输入框 | **记为已发**（宁可漏回，不可重复） |
| `residual` | 框内有残留 | 记为没发，下轮重试 |

为什么 `unknown` 要记已发：重复给同一个人发同样的话是最严重的体验事故（也是封号风险）。
漏回最多是慢，重复发是错。

---

## 5. 决策层：一条消息怎么被回掉

### 5.1 入口 `brain/flow.py::handle_one()`

两条路径：

```
快路径（默认）
  列表行预览文本 → 反查 sid → 库里拿最后一条 → 判定 → 出话
  省掉一次截图 + 一次 OCR（约 3.5s）

慢路径（反查失败时）
  进会话 → 截图 OCR 读气泡 → 文本反查 sid → 判定 → 出话
```

反查的前提：会话列表的「消息预览」就是 `chatmsg.text` 原文（短消息不截断）。
文本太短（"嗯""？"）会撞车，所以 <4 字只在**有红点**的会话里认。

### 5.2 进会话 `_enter()`

```python
for i in range(retries):          # 默认 2
    tap_node(row.node)
    snap, pg = wait_page(("chat",), timeout=8.0)
    if pg == "chat": return snap, pg
    # 失败：重新 dump，重新定位行（行可能被新消息顶下去）
    if not located: break          # ← 定位不到就**别点**，把 page 交还上层
```

最后那个 `break` 是血的教训：用旧坐标再点一次，可能点到完全不同的控件
（实测点中会话页顶部的铭牌 → 打开付费订阅页 → 页面吞返回键 → 整轮报废）。

### 5.3 「谁该回」的唯一判据 `pendingq.candidates()`

过滤链（顺序有意义）：

```
7 天窗口 → 设备存活校验（App 里还在不在）→ 冷却中跳过 → 已回跳过
→ 官方号跳过 → 新老交错 → 内容档位 → 20 分钟内优先
```

配套三个保护：

- **失败台账**：进会话失败记 `enter_fail`，`STALE_GIVEUP_H=24` 小时后放弃
- **空烧降级**：连续 3 轮一个都没回成 → 放行匹配（`PENDING_ZERO_MAX=3`）
- **重启预算**：`RESTART_PER_ROUND=2`，避免一轮里把所有僵尸会话都撞一遍

---

## 6. 生成层：一句话怎么被造出来

### 6.1 双通道

| 用途 | 通道 | 说明 |
|---|---|---|
| **出话** | 方舟（`ark_chat`） | 只此一条，**不做本地回退**（本地模型质量不达标） |
| **分析/简报** | Ollama 优先 → 失败回落方舟 | 分析可以容忍质量差一点，但要快 |

> 早期版本让出话也回退到本地模型，结果是"话风突变"，用户一眼看出不是人。

### 6.2 `think:false` 只有一个真开关

火山方舟兼容 OpenAI 协议，但 `enable_thinking` 参数在 `/v1/chat/completions` 端点**被忽略**。
只有原生 `/api/chat`（Ollama 风格）的 `think` 字段生效。
写在这里免得下一个人再试一遍。

### 6.3 提示词结构（V9）

```
system = 人设（persona）+ 她的档案（brief）+ 规则（rules）
user   = 她刚发来的原话
```

切换开关 `SOUL_PROMPT_V9=0` 可回退到旧的三段式（functon-call / hybrid）。
`persona` / `rules` / `prompt` / `gate` 四层分离，改哪层只测哪层。

### 6.4 硬闸 `engine/gate.py`

13 条规则，任意命中 → 整句作废 + 重写。核心几条：

| 规则 | 阈值 | 理由 |
|---|---|---|
| 长度 | `MAX_CHARS=40`，理想 `<=26` | 超过 40 字回复率明显下降 |
| 复读 | 与她上句相似度 | 复读是最明显的机器味 |
| 零信息应答 | "嗯""哦""好的" | 等于没回 |
| commit 型问句 | "你会不会…""你是不是…" | 逼对方表态，压力大 |
| 站外导流 | 平台名 / 链接 | 平台规则 |
| 昼夜语气错配 | 按时段分层 | `day / warm / tension` 三级 |

**注意**：硬闸是兜底，不是质量保证。它只负责拦「一定不能发」的，不负责「发得好」。

---

## 7. 主循环：一轮里都干了什么

`guard/daemon.py::cycle()` 的阶段顺序是**产品决策**，不要随意改：

```
① 奇遇铃      任何导航之前（否则按返回键会把铃误关）
② 红点/新消息  clear.sweep：双击置顶 → 逐条进会话 → 该回就回
③ 已读未回     pendingq：红点清完才走
④ 唤醒老友     24h 同人一次
⑤ 匹配         进主页建档 → 发开场白 → 【此处才检查抢占】
⑥ 账号轮转     榨干 或 连续在线超时
⑦ 空闲         分片 sleep，每 5s 扫一次铃
```

**抢占铁律**：匹配进行中如果有铃/新消息，**必须先把当前开场白发出去**再退出；
退出时**不点「匹配下一个」**，把这次匹配留着，下次进来判「已说过话」再前进。
这样既不浪费匹配次数，又能立刻响应消息。

已读未回阶段只允许在安全点抢占：候选开始前、列表翻屏每一屏后、搜索等待/轮询中。
不能在输入框已经灌字、发送三态尚未确认时中断，否则会增加重复发送风险。

每轮结束写一条 `data/state/metrics.jsonl` 的 `round_end`，待回阶段写
`pending_end`，候选结果变化时写 `candidates`。这些指标用于统计 P50/P95 延迟，
不要用普通文本日志做机器统计。

相关常量：

| 常量 | 值 | 含义 |
|---|---|---|
| `MATCH_EVERY` | 8.0s | 匹配尝试间隔（循环内） |
| `WAKE_EVERY` | 60.0s | 两次唤醒之间 |
| `IDLE_SLEEP` | 30.0s | 全空闲时的睡眠 |
| `ROUND_BUDGET` | 600.0s | 单轮时间预算 |
| `MATCH_STREAK_N` | 12 | 连匹上限（次数） |
| `MATCH_STREAK_BUDGET` | 420.0s | 连匹上限（时长） |
| `PENDING_ZERO_MAX` | 3 | 空烧多少轮后放行匹配 |

---

## 8. 数据层：为什么直读数据库

`data/imdb.py` 直接读模拟器里 App 私有目录下的明文 SQLite。

**为什么不从 UI 读**：UI 只显示最后一条 + 预览，拿不到完整历史、时间戳、消息类型。
没有这些就没法判断「她连发了几条」「最后一条到底是谁发的」。

**安全边界**：

```python
def _assert_readonly(sql):     # 出现 INSERT/UPDATE/DELETE/DROP 直接抛错
    ...
```

只读是硬约束——写 App 的数据库 = 数据损坏 + 封号风险。
所以「我发过什么」另存一份自己的台账（`data/pending.py`），不写回 App。

**缓存与失效**：库是 300s 拉取缓存（`REFRESH_S=300`），
所以「她刚发的话」可能还没进库 → 反查落空。这时强制拉一次（60s 节流）。

**设备库缩水保护**：Soul 会清历史，设备库可能突然从 12MB 变 600KB。
`本地镜像` 会保留并增量合并，绝不因为设备库变小就把本地数据覆盖掉。

---

## 9. 并发生命周期：锁、心跳、自愈

### 9.1 单实例锁 `guard/lock.py`

```python
os.open(path, O_CREAT | O_EXCL | O_WRONLY)   # 内核保证原子性
```

- 持锁进程死了 → 下次启动检测 pid 不存活 → 接管
- 接管用 `os.replace`（原子重命名），两个进程抢只有一个能成功
- 锁里带 `step` + `step_ts`：**这是判断进程是否卡死的第一手资料**

`HEARTBEAT_S=900` / `TTL_S=3300`。

### 9.2 三级设备自愈

| 级别 | 触发 | 动作 |
|---|---|---|
| L1 | 连续失败 ≥3 次 | `adb kill-server` → `start-server` → `connect` |
| L2 | ≥6 次 | `adb root` + 重建 `uiautomator2` 连接 |
| L3 | ≥9 次 | `taskkill MuMu` → `MuMuManager launch` 重建实例 |

两次自愈最短间隔 300s（`SOUL_DEV_RESCUE_L3=0` 可关掉 L3）。

**为什么需要**：历史上设备挂死过一次 2h46m，全程只有 `sleep 180s` 重试，没有任何自救动作。

### 9.3 看门狗

`watchdog.HANG_S=900` **必须大于** `daemon.ROUND_BUDGET=600`。
否则单轮跑满就被判卡死 → 重启 → 又跑满 → 再重启。
历史上这条被违反过，一天重启 186 次。

---

## 10. 关键常量总表

改之前先想清楚：**下面每个数字都对应一次实测**。

### 感知

| 常量 | 值 | 位置 | 含义 |
|---|---|---|---|
| `DUMP_TIMEOUT` | 20s | `eyes/uitree.py` | dump 兜底超时 |
| `LIST_Y_MIN` / `LIST_Y_MAX` | 130 / 1502 | `eyes/chatlist.py` | 列表可视区 |
| `ROW_MIN_H_RATIO` | 0.069 | `eyes/chatlist.py` | 行高下限（占屏比例） |
| `LIST_MIN_H_RATIO` | 0.5 | `eyes/chatlist.py` | 列表容器高度下限 |
| `MSG_TOP` / `MSG_BOTTOM` | 140 / 1400 | `eyes/chat.py` | 消息区上下界 |
| `RIGHT_EDGE` / `LEFT_EDGE` | 700 / 210 | `eyes/chat.py` | 气泡归属判据 |

### 动作

| 常量 | 值 | 位置 | 含义 |
|---|---|---|---|
| `FRAME_TTL` | 1.2s | `brain/act.py` | 帧缓存有效期 |
| `ACTION_GEN` | 计数器 | `core/device.py` | 动作代数（缓存失效） |
| `slow_factor()` | 1.0/1.5/2.5 | `core/device.py` | 慢设备放大幅度 |

### 业务

| 常量 | 值 | 位置 | 含义 |
|---|---|---|---|
| `MAX_N` | 5 | `brain/pendingq.py` | 单轮最多处理几个待回 |
| `FRESH_H` | 6 | `brain/pendingq.py` | 「新」的时间窗 |
| `LOOKBACK_DAYS` | 7 | `brain/pendingq.py` | 回溯窗口 |
| `SKIP_HOURS` | 3 | `brain/pendingq.py` | 失败后跳过时长 |
| `STALE_GIVEUP_H` | 24 | `brain/pendingq.py` | 多久后彻底放弃 |
| `MAX_ENTER` / `MAX_DOUBLE` | 8 / 5 | `brain/clear.py` | 清红点上限 |
| `FAKE_DOT_COOL_S` | 900 | `brain/clear.py` | 假红点冷却 |
| `MIN_MSGS` / `COLD_HOURS` | 10 / 12 | `brain/wake.py` | 唤醒候选门槛 |
| `MAX_PER_ROUND` | 2 | `brain/wake.py` | 单轮唤醒上限 |
| `WOKE_COOLDOWN_H` | 24 | `brain/wake.py` | 同人唤醒冷却 |
| `NEXT_TEXT` | "匹配下一个" | `brain/match.py` | 匹配按钮文案 |
| `CAP_H` / `CAP_WARN` | 200 / 150 | `brain/ratelimit.py` | 日发送配额 |

### 生成

| 常量 | 值 | 位置 | 含义 |
|---|---|---|---|
| `MAX_CHARS` / `IDEAL_MAX` | 40 / 26 | `brain/engine/gate.py` | 长度闸 |
| `_COLD_ACK_MAX` | 12 | `brain/engine/gate.py` | 她冷淡时的回复上限 |
| `LOCAL_MODEL` | qwen 系列 | `brain/engine/llm.py` | 分析用本地模型 |
| `BRAIN_TIMEOUT` | 40s | `brain/engine/llm.py` | 模型调用超时 |
| `OLLAMA_NUM_CTX` | 16384 | `brain/engine/llm.py` | 本地上下文长度 |

---

## 11. 已知坑与设计取舍

### 11.1 「点了没反应」有三种完全不同的原因

1. **点击丢了**（模拟器卡）→ 重试一次
2. **页面还没转场完**（dump 到半张图）→ 等，然后重新 dump
3. **坐标已经失效**（旧帧的坐标）→ **重新定位，别复用坐标**

第 3 种最危险，因为它会点到别的控件上。

### 11.2 「底栏还在」不等于「在主框架」

看似矛盾但真的发生过：底栏节点在树里，但页面是 `unknown`。
这时按返回键会**直接退出 App 到桌面**（用户定的铁律：主框架内永远点 tab，不按返回）。
所以 `unknown` 分支的新顺序是：**先试底栏 tab → 再考虑返回**。

### 11.3 `am start` 不带 `--activity-clear-top` 是空转

`am start -n <MainActivity>` 只是把**整个任务**提到前台，
叠在 MainActivity 之上的 H5 页 / RN 容器页仍在最上层——页面根本没变。
带 `--activity-clear-top` 才会清掉上面的页面。

**另一个坑**：判断「有没有回到主界面」不能只看包名。
H5Activity 和 MainActivity 是**同一个包**，用包名判定会得到「已回首页」的假成功。

### 11.4 H5 网页页会吞掉返回键

实测连按两次返回键，`mCurrentFocus` 仍然是 `H5Activity`。
所以「按返回退出子页」这条策略对 H5 页无效，必须用 clear-top。

> 这类页面在旧版架构里也踩过（当时用 `input keyevent 4` 能退），
> **重写时把解法丢了** —— 换架构前先翻一遍旧报告的「已修坑」。

### 11.5 红点角标会虚高

角标显示 3，但屏上一个行内红点都没有。
这种情况要判「虚高」并且**不挡后续流程**，否则匹配和唤醒永远轮不到。

### 11.6 日志有两套，别拿错

- `logs/<模块>.log` — `RotatingFileHandler`，每条 flush，**权威**
- `logs/daemon.out` — stdout 重定向副本，**会缓冲、可能 GBK 乱码**

判断进程卡死请看锁里的 `step`，不要看 `daemon.out` 有没有新行。

### 11.7 故意没做的事

| 没做 | 原因 |
|---|---|
| 逆向 App 私有接口 | 签名校验 + 封号风险远大于收益 |
| 语音**发送** | 合成音色一听就假，反而扣分 |
| 多设备并发 | 单实例锁按「一设备一进程」设计，改造收益不明 |
| 向量检索记忆 | 记忆文件全文拼进 prompt 就够，加向量库徒增故障点 |
| 本地模型出话 | 质量不稳定，话风突变 |
