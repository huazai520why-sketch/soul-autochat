# Soul AutoChat · 安卓 App 外挂式自动化框架

> 用 `adb + uiautomator2` 在**不修改、不注入、不逆向**任何 App 的前提下，
> 让一台安卓模拟器自己完成「读屏幕 → 判断该不该说话 → 生成内容 → 点发送」的完整闭环。

本仓库是一个**真实的、跑在生产环境里的**自动化项目源码：它在 MuMu 模拟器里 7×24 跑了一个多月，
每天处理几百条消息。代码里保留了大量「踩坑注释」——每一段 `🔴` 开头的注释都对应一次真实故障。

---

## ⚠️ 先说清楚：这是什么、能拿来干什么

**技术本质**：一套「手机屏幕自动化」的工程实践。核心不是"聊天机器人"，
而是 **如何在不稳定的 GUI 上做可靠的感知与动作**——屏幕会转场、控件会改版、点击会丢、App 会卡死。
所有代码都在解决这一类问题，这部分可以迁移到任何 App 自动化场景。

**必须知道的限制**：

| 项 | 说明 |
|---|---|
| 平台规则 | 自动操作社交 App **通常违反其用户协议**，账号可能被限制或封禁。作者不对使用后果负责。 |
| 法律边界 | 请遵守所在地法律（如《个人信息保护法》）。**不要**用它批量骚扰、诈骗、爬取他人信息。 |
| 内容责任 | 你说出去的话由你负责。仓库里的「硬闸」（`brain/engine/gate.py`）是一层**兜底过滤**，不是免责。 |
| 本项目定位 | 自用工具 + 自动化工程参考。**不是**给多租户用的 SaaS，没有账号体系、没有多设备调度。 |

**如果你只是来学自动化**：直接看 `core/`（设备层）→ `eyes/`（感知层）→ `hands/`（动作层）→ `brain/act.py`（帧复用），
这四块是通用能力，跟"聊天"无关。

---

## 目录

- [它能做什么](#它能做什么)
- [它是怎么工作的](#它是怎么工作的)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [目录结构](#目录结构)
- [几个关键设计（为什么这么写）](#几个关键设计为什么这么写)
- [排障：出问题先看这三处](#排障出问题先看这三处)
- [隐私与脱敏](#隐私与脱敏)
- [FAQ](#faq)

**延伸文档**

| 文档 | 内容 |
|---|---|
| [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md) | 当前生产架构图：计划任务、进程拓扑、包依赖、主链路和清理边界 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构详解：分层、数据流、一次读屏/点击的完整过程、关键常量总表、已知坑 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | 部署与运行：从零到跑起来、排障速查、**改代码的铁律** |
| [docs/TREE.md](docs/TREE.md) | 目录树：每个文件一行说明，外加「我想做什么 → 去哪个文件」对照表 |

---

## 它能做什么

| 能力 | 状态 | 实现位置 |
|---|---|---|
| 读屏幕（UI 树 + 截图 OCR 双通道） | ✅ | `eyes/uitree.py`、`eyes/chat.py` |
| 识别当前在哪个页面 | ✅ | `eyes/page.py::detect()` |
| 清未读红点（双击置顶 + 逐条进会话） | ✅ | `brain/clear.py` |
| 必回：进来一条消息就回一条 | ✅ | `brain/flow.py`、`brain/reply.py` |
| 补「已读未回」（对方发了、我看过但没回） | ✅ | `brain/pendingq.py` |
| 主动唤醒沉默老友 | ✅ | `brain/wake.py` |
| 「灵魂匹配」自动开场白 | ✅ | `brain/match.py` |
| 语音消息转文字（faster-whisper） | ✅ | `brain/asr.py`、`brain/voice.py` |
| 发图片 | ✅ | `hands/pic.py` |
| 奇遇铃（弹窗抢救） | ⚠️ | `brain/bell.py`（需要 OCR，见注释） |
| 多账号轮转（榨干/超时切号） | ⚠️ | `brain/acct.py`（逻辑完整，UI 路径需按版本校准） |
| 崩溃自愈 / 设备自愈 | ✅ | `guard/daemon.py`、`tools/devwatch.py` |
| 单实例锁 + 心跳 | ✅ | `guard/lock.py` |

---

## 它是怎么工作的

### 五层架构

```
┌──────────────────────────────────────────────────────────────┐
│  guard/   守护层：主循环、单实例锁、看门狗、设备自愈            │
│           daemon.py 每轮按「铃 → 红点 → 已读未回 → 唤醒 → 匹配」│
│           → 切号 → 空闲 的顺序跑                               │
└───────────────────────────┬──────────────────────────────────┘
                            │ 调用
┌───────────────────────────▼──────────────────────────────────┐
│  brain/   决策层：业务规则。谁该回、回什么、能不能发            │
│           flow（进会话→判定→出话）、pendingq（找待回）、        │
│           reply（生成）、engine/gate（硬闸过滤）                │
└───────────────────────────┬──────────────────────────────────┘
                            │ 调用
┌───────────────────────────▼──────────────────────────────────┐
│  eyes/    感知层：只读，不点。UI 树 + OCR 两条通道              │
│  hands/   动作层：只动，不判。点击 / 输入 / 发图                │
└───────────────────────────┬──────────────────────────────────┘
                            │ 调用
┌───────────────────────────▼──────────────────────────────────┐
│  core/    设备层：adb、uiautomator2、截图、路径、日志、慢设备因子│
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  data/    数据层：直读 App 私有目录里的明文 SQLite             │
│           （只读！见 imdb.py 的 _assert_readonly）              │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向是单向的**：`guard → brain → eyes/hands → core`。
`eyes` 不许 import `hands`，`hands` 不许 import `eyes`。这条规则让「读」和「写」永远可以单独测试。

> 当前跨层依赖违规已清零：冷却/已回台账下沉到 `data/pending_ledger.py`，
> 消息分类下沉到 `core/message_kind.py`，`run.py match` 走 `brain/match_runner.py`。

### 一次「她发消息 → 我回复」的完整时间线

这是全项目最核心的一条链路，看懂这一条就懂 80%：

| 步 | 动作 | 代码 | 耗时 |
|---|---|---|---|
| 1 | 双击「聊天」tab，把列表置顶并读角标 | `brain/clear.py` | ~1.5s |
| 2 | dump UI 树，解析出会话行 + 红点 + 预览文本 | `eyes/uitree.py`、`eyes/chatlist.py` | 2~4s |
| 3 | 用**列表行的预览文本**反查会话 id（省一次 OCR） | `brain/flow.py::sid_from_row` | 0.05s |
| 4 | 点这一行，等页面变成 `chat` | `brain/act.py::tap_node` + `wait_page` | 0.5~8s |
| 5 | 从数据库读「她最后一条」，判断是我发的还是她发的 | `data/imdb.py` | 0.05s |
| 6 | 组装 prompt（人设 + 她的档案 + 最近对话）调模型 | `brain/engine/llm.py` | 1~5s |
| 7 | 过「硬闸」：太长 / 踩红线 / 复读 / 空话 → 作废重写 | `brain/engine/gate.py` | 0.01s |
| 8 | 点输入框、灌字、点发送 | `hands/input.py` | 1~3s |
| 9 | 校验有没有真发出去（输入框是否清空） | `hands/input.py::sent_ok` | 0.5~2s |

**单条约 8~20 秒**。慢的原因 90% 是第 2 步的 dump（一次 2~4s），所以有了下面第 1 个关键设计。

---

## 快速开始

### 环境要求

- **Windows 10/11**（本项目在 Windows 上开发；核心逻辑跨平台，但自愈脚本是 Windows 专用）
- **Python 3.11+**
- **安卓模拟器**（推荐 MuMu 12 / Android 12+）或真机，需开启 **root**（要读 App 私有目录里的数据库）
- **adb**（模拟器自带，或独立安装的 platform-tools）

### 安装

```bash
git clone https://github.com/huazai520why-sketch/soul-autochat.git
cd soul-autochat

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 配置（三步）

```bash
# 1) 复制配置模板
copy config\model.env.example config\model.env      # Windows
cp config/model.env.example config/model.env        # macOS/Linux

# 2) 放进你的模型密钥（本项目用火山方舟，任意 OpenAI 兼容端点都行）
#    在项目根目录建一个 .ark_key 文件，把 key 写进去（一行，别加引号）
echo YOUR_API_KEY > .ark_key

# 3) 改 adb 路径（如果不在默认位置）
#    编辑 core/paths.py 的 ADB_CANDIDATES，或设环境变量 SOUL_ADB
```

### 先自检，再跑

```bash
python run.py check      # 环境自检：设备 / root / 截图 / UI树 / 数据库 / 模型，全绿再往下
python run.py screen     # 只读屏，把当前页面和会话行打出来（不发任何消息）
python run.py once --dry # 跑一轮，但**不真的发送**（dry-run，强烈建议先跑这个）
```

确认无误后：

```bash
python run.py daemon     # 常驻主循环
```

### 常用命令

```bash
python run.py check            # 自检
python run.py screen           # 读一次屏
python run.py once             # 跑一轮就退出
python run.py once --dry       # 跑一轮但只打印不发送
python run.py daemon           # 常驻
python run.py watchdog         # 看门狗（守护 daemon，另开一个终端）
python run.py clear            # 只清一轮红点
python run.py pending 5        # 只处理 5 个「已读未回」
python run.py match 3          # 只跑 3 轮匹配
python run.py bell             # 只盯奇遇铃（别和 daemon 同时开）
```

---

## 配置说明

所有可变配置都在 `config/model.env`（**已被 gitignore，不会进仓库**）。完整模板见
[`config/model.env.example`](config/model.env.example)，逐项含义：

| 键 | 作用 | 默认 |
|---|---|---|
| `SOUL_ARK_URL_DIRECT` | 出话模型端点（OpenAI 兼容） | 火山方舟 |
| `SOUL_ARK_MODEL_DIRECT` | 出话模型名 | `deepseek-v4-1-flash-261017` |
| `SOUL_ARK_KEY` | 模型密钥（也可放 `.ark_key` 文件） | 空 |
| `SOUL_LOCAL_URL` / `SOUL_OLLAMA_URL` | 本地 Ollama 端点（分析/简报用） | `127.0.0.1:11434` |
| `SOUL_FLOW` | 出话流程：`direct`（直连）/ `hybrid` / `fc` | `direct` |
| `SOUL_PROMPT_V9` | 提示词结构：`1` = 人设+档案进 system | `1` |
| `SOUL_TENSION_START` | 从几点开始用「夜间档」语气（小时） | `23` |
| `SOUL_MY_CONTACT` | 你自己的联系方式（**别写进源码**） | `13800138000`（示例） |
| `SOUL_IDLE_SWITCH_MIN` | 空闲多少分钟切号 | `30` |
| `SOUL_RESTART_MIN_GAP` | 两次重启 App 的最小间隔（秒） | `240` |
| `SOUL_MY_CONTACT` | 见上 | — |

> 🔒 **密钥永远不进仓库**。`brain/engine/llm.py::ark_key()` 的读取顺序：
> `SOUL_ARK_KEY` 环境变量 → `BASE/.ark_key` 文件。两个位置都在 gitignore 里。

---

## 目录结构

```
soul-autochat/
├─ run.py                     唯一入口（check/screen/once/daemon/watchdog/...）
├─ requirements.txt
├─ config/
│  ├─ model.env.example       ✅ 进仓库的模板
│  └─ model.env               ❌ 你的真实配置（gitignore）
├─ core/                      ── 设备层：和手机打交道
│  ├─ device.py               adb 封装、root、截图、动作代数、慢设备因子
│  ├─ paths.py                路径常量、adb 候选路径、包名
│  ├─ log.py                  统一日志（UTF-8 + 行缓冲 + 按模块分文件）
│  ├─ metrics.py              JSONL 结构化运行指标
│  └─ message_kind.py         纯消息分类（human/system/ad）
├─ eyes/                      ── 感知层：只读，不点
│  ├─ uitree.py               dump UI 树 → Snapshot；hit()/tab() 三级定位
│  ├─ page.py                 页面识别 detect()、底栏角标 badges()
│  ├─ chatlist.py             会话列表解析（行的判定、下钻、红点）
│  ├─ chat.py                 会话页气泡归属（左/右）
│  ├─ profile.py              个人主页信息抓取
│  ├─ popup.py                弹窗识别（只识别，不决策）
│  └─ ocr.py                  OCR 封装
├─ hands/                     ── 动作层：只动，不判
│  ├─ tap.py                  点击（统一入口，动作后使帧缓存失效）
│  ├─ input.py                输入框灌字、发送、三态校验
│  └─ pic.py                  发图片
├─ brain/                     ── 决策层：业务规则
│  ├─ act.py                  Actor：帧复用、动作后确认、快照缓存
│  ├─ nav.py                  导航：回到某个 tab（带升级梯子）
│  ├─ flow.py                 进会话 → 判定 → 出话 → 发送（主链路）
│  ├─ clear.py                清红点
│  ├─ pendingq.py             「已读未回」候选池（唯一待回判据）
│  ├─ pending_policy.py       纯候选排序与冷却策略
│  ├─ reply.py                出话编排（几条、怎么拆、失败兜底）
│  ├─ match.py                匹配 + 开场白
│  ├─ match_runner.py         `run.py match` 的生产运行器
│  ├─ wake.py                 唤醒沉默老友
│  ├─ search.py               搜索定位会话（列表翻不到时的兜底）
│  ├─ bell.py                 奇遇铃
│  ├─ voice.py / asr.py       语音转写
│  ├─ acct.py                 多账号轮转
│  ├─ casepack.py             画像/案情包
│  ├─ ratelimit.py            发送配额
│  ├─ scheduler.py            时段策略
│  ├─ env.py                  环境探测
│  ├─ localq.py / picreq.py / stage*.py    辅助模块
│  └─ engine/                 ── 出话引擎
│     ├─ llm.py               模型调用（方舟 / Ollama / 兼容端点）
│     ├─ prompt.py            提示词组装（当前 v9）
│     ├─ persona.py           人设（身份表插值，避免多账号串味）
│     ├─ rules.py             出话规则层
│     ├─ brief.py             「她的简报」压缩
│     ├─ opener.py            开场白
│     └─ gate.py              🔒 硬闸：13 条拒绝规则
├─ guard/                     ── 守护层
│  ├─ daemon.py               主循环 cycle()（七阶段）
│  ├─ lock.py                 单实例锁（O_EXCL 原子创建 + 死锁接管）
│  └─ watchdog.py             看门狗
├─ data/                      ── 数据层
│  ├─ imdb.py                 直读 App 明文 SQLite（**严格只读**）
│  ├─ pending.py              待回台账
│  ├─ pending_ledger.py       共享冷却/已回复台账
│  └─ watch.py                数据库变更监听
├─ tools/                     ── 运维脚本
│  ├─ silent_launch.py        所有 Soul 计划任务统一静默启动
│  ├─ _silent/                子进程无窗口注入（禁止删除）
│  ├─ msg_probe.py            消息探针（每 15s 查一次新消息）
│  ├─ devwatch.py             设备存活守护（offline 自动重建）
│  ├─ watchdog_live.py        进程守护
│  ├─ logrotate.py            日志滚动
│  ├─ crash_alert.py          崩溃告警
│  ├─ cost_watch.py           模型花费统计
│  ├─ daily_review.py         每日复盘
│  ├─ voice_check.py          语音链路自检
│  ├─ prepare_photos.py       照片进相册（发图前置）
│  └─ *.ps1                   Windows 计划任务注册脚本
├─ scripts/repo_sync.ps1      Git 漂移检查与脱敏扫描
├─ tests/                     ── 26 个保留验收/回放与离线脚本（t_*.py）
└─ docs/                      ── 架构与部署文档
```

---

## 几个关键设计（为什么这么写）

这一节是本项目的「灵魂」。每条都是被故障逼出来的。

### 1. 帧复用 + 动作代数（把 dump 从 4s 降到 0）

`dump UI 树` 一次要 2~4 秒，而一轮要做十几次判断。
`brain/act.py` 缓存上一次的 Snapshot，`FRAME_TTL=1.2` 秒内复用。
但缓存必须能**立刻失效**——所以有了两个守卫：

- **动作代数**：`core/device.py::note_action()`，任何改屏动作 `ACTION_GEN += 1`，所有旧帧作废。
  这样即使绕过 `Actor` 直接调 `u2`，缓存也不会脏。
- **Activity 比对**：缓存帧会记住当时的 `mCurrentFocus`，页面变了就不复用。

> 教训来源：早期「点完还拿旧坐标继续点」导致连续误触，最严重一次点开了付费订阅页。

### 2. 三级控件定位（`Snapshot.hit()`）

UI 树里「能看见的」和「能点的」经常不是同一个节点。
底栏的「聊天」文字是 `TextView`，可点的是它**兄弟**节点的 `View`。
所以 `hit()` 依次尝试：自身 clickable → 上溯祖先 → **几何反查**（找包含该中心点的最小 clickable 节点）。

### 3. 发送三态，而不是「发出去了」

点完「发送」不能假设成功。`hands/input.py::sent_ok()` 返回三种：

| 状态 | 判断依据 | 后续处理 |
|---|---|---|
| `ok` | 输入框已清空 | 正常记账 |
| `unknown` | 读不到输入框（页面已变） | **按已发记账**（宁可漏回，不可重复骚扰） |
| `residual` | 输入框还有残留 | 明确没发，不记账，下轮重试 |

这条直接决定「会不会给同一个人发两遍」。

### 4. 「唯一待回判据」只在一个地方

判断「谁该回」的逻辑**只允许**出现在 `brain/pendingq.py::candidates()`。
早期这套逻辑散落在 5 个地方，各自加了过滤器，结果 A 认为该回、B 认为不该回，
同一人被连回 5 次。现在所有调用方（红点、已读未回、匹配闸门）都必须问它。

### 5. 硬闸优先于「话术好不好」

`brain/engine/gate.py` 有 13 条拒绝规则，任意一条命中整句作废并重写：
长度超限（40 字）、红线词、性邀约结构句、空头承诺、**复读**（和她上句高度相似）、
零信息应答（"嗯""哦"）、commit 型问句、昼夜语气错配、站外导流。
`MAX_CHARS=40 / IDEAL_MAX=26` 是实测出来的——超过 40 字回复率明显下降。

### 6. 单实例锁必须是原子的

`guard/lock.py` 用 `O_EXCL` 创建锁文件，只有内核保证「只有一个进程能创建成功」。
死锁接管用 `os.replace` 原子重命名——两个进程同时抢，只有一个能搬走旧锁。
**不要**改成「先读再判断再写」，那在并发下必然出双实例，
而双实例 = 同一个人被两个进程各回一次。

### 7. 看门狗的超时必须大于单轮预算

`watchdog.HANG_S=900` 必须大于 `daemon.ROUND_BUDGET=600`。
否则「干活越卖力越容易被判卡死」——历史上这条规则被违反过一次，
导致一天重启 186 次。

---

## 排障：出问题先看这三处

```bash
# ① 进程到底活着没？（别看 stdout，看锁里的 step 在不在动）
type data\state\daemon.lock

# ② 权威日志（按模块分文件，每条都 flush）
tail -f logs\guard.daemon.log
tail -f logs\brain.flow.log
tail -f logs\brain.pendingq.log

# ③ 设备在哪一层？
python run.py screen
adb shell dumpsys window | findstr mCurrentFocus
```

**判断进程"卡死"的正确姿势**（三处一起看，缺一不可）：

1. `data/state/daemon.lock` 里的 `step` 有没有变化
2. `logs/guard.daemon.log` 有没有新增行
3. 进程的 CPU 时间有没有在累加

> ⚠️ `logs/daemon.out` **只是 stdout 的副本**，会随启动方式被块缓冲甚至 GBK 乱码。
> 拿它判断死活会误判——本项目就踩过这个坑。

---

## 隐私与脱敏

本仓库从私人生产环境开源而来，已做以下处理：

| 处理项 | 做法 |
|---|---|
| 模型密钥 | 源码从不硬编码；只从 `SOUL_ARK_KEY` 环境变量或 `.ark_key` 文件读 |
| 联系方式 | 移出源码，改由 `SOUL_MY_CONTACT` 读取；仓库里只有示例号 `13800138000` |
| 内网地址 | 默认值改为 `127.0.0.1`，真实地址走环境变量 |
| 他人身份 | 代码注释里出现的用户 ID 已全部打码为 `uid=***` |
| 个人路径 | 硬编码的 `C:\Users\<name>\...` 已改为自动探测 |
| 聊天内容 | `logs/`、`data/memory/`、`*.db`、截图 全部不进仓库（见 `.gitignore`） |

**请你自己部署时也守住这条线**：真实密钥、真实号码、任何人的聊天记录，都不该进 git。

---

## FAQ

**Q：为什么不用 App 的 API，非要模拟点击？**
A：没有公开 API；逆向私有接口风险更高（签名校验 + 封号）。模拟点击是「最笨但最稳」的路子，
代价是慢、依赖 UI 结构，所以代码里到处是"结构判据优先、文案兜底"。

**Q：为什么一会儿用 UI 树、一会儿用 OCR？**
A：UI 树准且快（拿得到 resource-id），但很多弹窗是**自绘**的，树里根本没有节点（比如奇遇铃）。
默认走树，树里找不到线索才 OCR。OCR 一次约 2.5~3.5s，能不用就不用。

**Q：单条回复为什么要 8~20 秒？**
A：dump UI 树 2~4s 是主要开销，模型 1~5s，点击与等待 3~6s。
想更快要先解决 dump——本项目用「帧复用」把大部分 dump 省掉了，剩下的省不掉。

**Q：能同时跑多台设备 / 多个账号吗？**
A：多账号有（`brain/acct.py` 轮转，同一时刻只有一个在前台）；多设备**没有**。
单实例锁是按「一台设备一个进程」设计的。

**Q：跑起来一直 `unknown` 页怎么办？**
A：先 `python run.py screen` 看当前 `mCurrentFocus`。如果是 `H5Activity`（网页页），
本项目已内置逃逸（`am start --activity-clear-top`）。如果是新版本 App 改了 UI，
需要更新 `eyes/page.py::SIG` 里的特征文本。

**Q：会不会把人聊崩？**
A：有硬闸 + 长度限制 + 复读检测 + 「她冷就撤」规则，但**没有**质量保证。
这是自动化工具，不是情感产品。

---

## 许可

MIT License，见 [LICENSE](LICENSE)。

再次强调：**自动化操作第三方 App 通常违反其用户协议**。本仓库仅作技术参考，
使用前请自行评估账号风险与法律合规性。
