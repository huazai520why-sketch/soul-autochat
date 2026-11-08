# 部署与运行

> 从零到跑起来。按顺序做，每步都有验证方法——**不要跳过验证直接进下一步**。

---

## 0. 先明确你要什么

| 目标 | 需要的步骤 |
|---|---|
| 只想看代码 / 学自动化 | 克隆 + 读 `docs/ARCHITECTURE.md`，不用装环境 |
| 想在自己电脑上跑起来 | 全部步骤 |
| 想改代码 | 全部步骤 + 读第 6 节「改代码的铁律」 |

---

## 1. 准备安卓环境

### 1.1 模拟器（推荐）

- **MuMu 模拟器 12**（Android 12），分辨率设成 **900×1600**，DPI 320
- 在模拟器设置里打开 **root**
- 记下 adb 端口，MuMu 默认是 `127.0.0.1:16384`

> 为什么必须 900×1600：本项目所有坐标常量都基于这个分辨率实测。
> 换分辨率不是不能跑，但 `eyes/chat.py` 的气泡归属阈值（`RIGHT_EDGE=700` 等）需要重新标定。

### 1.2 真机（可行但不推荐）

真机需要 root（要读 App 私有目录的数据库），并且 adb 要能连上。
没 root 的话 `python run.py check` 会在「数据库」那步失败，
此时只有「读屏」和「点击」能力，业务链路跑不通。

### 1.3 验证设备连上了

```bash
adb devices
# 应该看到类似：
# 127.0.0.1:16384   device

adb shell wm size
# Physical size: 900x1600

adb root
# restarting adbd as root     ← 必须看到这行
```

`adb root` 失败通常是模拟器没开 root 权限。

---

## 2. 装 Python 环境

```bash
git clone https://github.com/huazai520why-sketch/soul-autochat.git
cd soul-autochat

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

python -m pip install -U pip
pip install -r requirements.txt
```

`faster-whisper` 首次运行会下载模型（默认 `small`，约 500MB）。
不想下可以把 `SOUL_ASR=0` 关掉语音转写——只是语音消息会回不了。

---

## 3. 配置

```bash
copy config\model.env.example config\model.env
```

然后改三处：

1. **模型端点与模型名**（`SOUL_ARK_URL_DIRECT` / `SOUL_ARK_MODEL_DIRECT`）
   任何 OpenAI 兼容端点都行，不一定非火山方舟。
2. **密钥**：在项目根目录建 `.ark_key`，写入一行 key（不要引号）
   ```
   YOUR_API_KEY_HERE
   ```
3. **adb 路径**（如果你的 adb 不在默认位置）
   编辑 `core/paths.py` 的 `ADB_CANDIDATES`，或设环境变量 `SOUL_ADB`。

> 🔒 `.ark_key` 和 `config/model.env` 都在 `.gitignore` 里。
> **提交前一定确认 `git status` 里看不到它们。**

---

## 4. 自检（关键一步）

```bash
python run.py check
```

它会逐项检查并打印结果：

| 检查项 | 失败时的处理 |
|---|---|
| adb 可用 | 装 platform-tools 或改 `ADB_CANDIDATES` |
| 设备已连接 | `adb connect 127.0.0.1:16384` |
| 有 root | 模拟器设置里打开 root，然后 `adb root` |
| 能截图 | 设备卡了，重启模拟器 |
| 能 dump UI 树 | `uiautomator2` 没装好，或服务端没起来 |
| 能读数据库 | 没 root，或 App 还没登录过 |
| 模型可用 | key 不对 / 端点不对 / 网络不通 |

**全绿再往下。** 任何一项红着，后面都会以奇怪的方式失败。

---

## 5. 干跑（dry-run）

```bash
python run.py screen          # 只读屏，打印页面类型和会话行
python run.py once --dry      # 跑一轮，全程只打印，不发送任何消息
```

`screen` 的输出应该能看到：

```
page=chatlist
会话行 12，其中红点 3
  y=316   [红点2] 某某某 · 在吗
  y=470            某某 · 好呀
```

如果 `page=unknown`，说明 App 版本改了 UI 结构，需要更新 `eyes/page.py::SIG`。

`once --dry` 会走完「选人 → 生成 → 过闸」，最后一步不点发送。
看一遍它打算发什么，确认口吻和长度符合预期。

---

## 6. 正式运行

```bash
python run.py daemon
```

建议**另开一个终端**跑看门狗：

```bash
python run.py watchdog
```

### Windows 开机自启（可选）

`tools/` 下有现成的计划任务注册脚本：

```powershell
powershell -ExecutionPolicy Bypass -File tools\reg_ops_tasks.ps1
```

它会注册几个任务（日志滚动、消息探针、每日复盘等）。
**先打开脚本看一遍**再执行——不同机器路径不一样。

---

## 7. 改代码的铁律

这一节是这个项目最重要的经验。改之前请务必读完。

### 7.1 绝对不能碰的顺序

1. **先作废缓存，再动手**：`dev.note_action()` 必须在点击之前调用。
2. **动作之后永不复用旧帧**：`_after(force=True)`。
3. **主框架内绝不按返回键**：底栏还在就点 tab，按返回会直接退到桌面。
4. **重定位失败就不要点**：宁可放弃这一轮，也不要用旧坐标盲点。

4 条里任何一条被违反，症状都是「偶尔点到奇怪的东西」，极难查。

### 7.2 改完必须做的验证

```bash
# ① 语法
python -m py_compile <改的文件>

# ② 真导入（语法过了运行时才炸的例子很多）
python -c "import brain.nav, brain.flow, guard.daemon; print('ok')"

# ③ 真实调用路径（**不能只做前两步**）
python run.py screen
python run.py once --dry
```

历史上吃过亏：`fails` 变量忘了初始化，`py_compile` 全过，
但 `to_tab()` 第一行就抛 `UnboundLocalError`，**每一轮都在同一处崩**，机器人直接停摆。

### 7.3 新增常量请写清楚「为什么是这个值」

本项目每个阈值背后都有一次实测。只写数字不写理由，
下一个人就会"顺手调大一点"，然后线上出问题。

### 7.4 改 UI 相关的代码前先 dump 一次

```bash
python run.py screen
```

看清楚当前版本的真实结构，不要照着注释里的旧结构改。

---

## 8. 排障速查

| 症状 | 先看这里 |
|---|---|
| 一直 `unknown` | `adb shell dumpsys window \| findstr mCurrentFocus`。是 `H5Activity` 就是网页页（已内置 clear-top 逃逸）；否则是 App 改版，更新 `page.py::SIG` |
| 机器人不动，但进程在 | `type data\state\daemon.lock` 看 `step` 有没有变；再看 `logs\guard.daemon.log` 有没有新行 |
| 同一个人被回两次 | 查 `hands/input.py::sent_ok` 的三态记账；查 `pendingq` 的台账 |
| 回复特别慢 | 看 `logs\brain.flow.log` 里 dump 耗时；`slow_factor()` 是否被误判成慢设备 |
| 点到奇怪的地方 | 一定是「旧坐标复用」或「没等转场」 |
| 设备离线 | `adb connect` → `adb root` → 重启模拟器（`tools/devwatch.py` 会自动做前两步） |
| 日志是乱码 | 看 `logs\<模块>.log`，不要看 `daemon.out` |

---

## 9. 常用环境变量速查

| 变量 | 作用 |
|---|---|
| `SOUL_ARK_KEY` | 模型密钥（优先于 `.ark_key` 文件） |
| `SOUL_FLOW` | 出话流程（`direct` 推荐） |
| `SOUL_PROMPT_V9` | 提示词结构开关 |
| `SOUL_TENSION_START` | 夜间档起始小时 |
| `SOUL_MY_CONTACT` | 你自己的联系方式 |
| `SOUL_ASR` | `0` 关闭语音转写 |
| `SOUL_IDLE_SWITCH_MIN` | 空闲切号阈值（分钟） |
| `SOUL_RESTART_MIN_GAP` | 重启 App 节流（秒） |
| `SOUL_DEV_RESCUE_L3` | `0` 关闭「重建模拟器」级自愈 |
| `SOUL_ADB` | adb 可执行文件路径 |

> 提示：`acct.py` 里 `IDLE_SWITCH_MIN` 只有一个定义点（读上面的环境变量）。
> 如果你在文件里搜到别的赋值，那是历史遗留，改了不生效。
