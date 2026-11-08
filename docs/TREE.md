# 目录树

> 每个文件一行说明。想快速定位「某个功能在哪」，从这里查。

```
soul-autochat/
│
├─ run.py                          ★ 唯一入口：check/screen/once/daemon/watchdog/wake/match/clear/pending/bell
├─ requirements.txt                依赖清单
├─ LICENSE                         MIT
├─ README.md                       项目总览（先看这个）
│
├─ config/
│  ├─ model.env.example            ✅ 配置模板（进仓库）
│  └─ model.env                    ❌ 你的真实配置（gitignore）
│
├─ core/                           ── 设备层：和手机打交道的唯一入口
│  ├─ __init__.py
│  ├─ device.py                    adb 封装、root 保活、截图(PNG 校验)、
│  │                               note_action() 动作代数、slow_factor() 慢设备因子、
│  │                               ensure_root()、probe_serial() 自动探测设备
│  ├─ paths.py                     路径与常量：ADB_CANDIDATES、SOUL_PKG、DEV_W/DEV_H、
│  │                               TAB_TEXTS、MUMU_MANAGER_CANDIDATES
│  └─ log.py                       统一日志：UTF-8 + 行缓冲 + 按模块分文件(RotatingFileHandler)
│
├─ eyes/                           ── 感知层：只读，绝不产生副作用
│  ├─ __init__.py
│  ├─ uitree.py                    dump UI 树 → Node/Snapshot；
│  │                               hit() 三级定位、tab() 底栏、signature() 页面指纹、
│  │                               DUMP_TIMEOUT 线程兜底
│  ├─ page.py                      detect() 页面识别（7 种）、badges() 底栏角标、
│  │                               SIG 各页特征文本
│  ├─ chatlist.py                  会话列表解析：list_view() 三约束 → _descend_to_rows()
│  │                               → rows() 双闸（行高 6.9% + 内容非空）；
│  │                               has_dot_now() 红点判定、_TIME_RES 时间格式正则
│  ├─ chat.py                      会话页气泡：bubbles()、last_bubble()、side_of()
│  │                               （MSG_TOP/BOTTOM、RIGHT_EDGE/LEFT_EDGE）
│  ├─ profile.py                   个人主页信息抓取（昵称/画像/标签/瞬间）
│  ├─ popup.py                     弹窗识别（只识别不决策）：Popup、detect()、signature()
│  └─ ocr.py                       OCR 封装（rapidocr）：read()、lines()、Item 框坐标
│
├─ hands/                          ── 动作层：只动，绝不判断
│  ├─ __init__.py
│  ├─ tap.py                       _do() 统一点击入口（先 note_action 再点，失败重连重试）
│  ├─ input.py                     输入框：BOX_RES/SEND_RES/PLACEHOLDER、
│  │                               send()、sent_ok() 三态校验(ok/unknown/residual)
│  └─ pic.py                       发图片：更多 → 图片 → 相册 → 选图 → 发送
│
├─ brain/                          ── 决策层：业务规则都在这里
│  ├─ __init__.py
│  ├─ act.py                       ★ Actor：帧复用(FRAME_TTL=1.2)、快照缓存、
│  │                               tap_node/tap_tab/wait_page、_after(force=True)
│  ├─ nav.py                       ★ 导航：to_tab() 升级梯子（点 tab→双击→back→
│  │                               am start→重启）、at_main() 按 Activity 判定、
│  │                               goto_main() 带 --activity-clear-top、restart_app() 节流
│  ├─ flow.py                      ★ 主链路：handle_one() 快/慢路径、_enter() 进会话、
│  │                               read_session()、sid_from_row() 行文本反查 sid、
│  │                               _reply_and_send()、her_burst() 连发合并
│  ├─ clear.py                     清红点：sweep()、双击置顶、假红点判定、MAX_ENTER/MAX_DOUBLE
│  ├─ pendingq.py                  ★「已读未回」候选池：candidates() 唯一待回判据、
│  │                               find_row() 列表定位、搜索兜底、失败台账、冷却
│  ├─ reply.py                     出话编排：engine()、generate()、target_n()（回几条）、
│  │                               FALLBACK_LINES 兜底话术、MEDIA_REPLIES
│  ├─ match.py                     「灵魂匹配」：进星球页 → 建档 → 发开场白、
│  │                               NEXT_TEXT 匹配下一个、抢占铁律
│  ├─ wake.py                      唤醒沉默老友：plan()、MIN_MSGS/COLD_HOURS、
│  │                               mark_woke() 台账、WOKE_FAIL_COOL_S
│  ├─ search.py                    搜索定位：dismiss_popups() 清运营弹窗、enter_first()、
│  │                               _BREAKER 熔断、LAST_REASON
│  ├─ bell.py                      奇遇铃：OCR 识别「立即私聊」→ 点 → 发开场白
│  ├─ voice.py                     语音消息：下载音频 → 调 asr → 当文本处理
│  ├─ asr.py                       faster-whisper 封装（SOUL_ASR 可关）
│  ├─ acct.py                      多账号轮转：quota 检查、8h/10h 强制切号、空闲切号、
│  │                               switch_book.json 台账
│  ├─ casepack.py                  案情包：她的画像 → L0~L4 分层存储
│  ├─ ratelimit.py                 发送配额：CAP_H/CAP_WARN → data/state/send_cap.json
│  ├─ scheduler.py                 时段策略（day/warm/tension）
│  ├─ env.py                       环境探测（状态覆盖、端口预检）
│  ├─ localq.py                    本地出话队列/调试日志
│  ├─ picreq.py                    要不要发图的判定
│  ├─ stage.py / stage_v12.py      话术分层（哪一轮该说什么）
│  └─ engine/                      ── 出话引擎
│     ├─ __init__.py               respond() 统一出口、MAX_N
│     ├─ llm.py                    ★ 模型调用：ark_chat()/analyze()、
│     │                            ark_key() 密钥读取、think:false 真开关、
│     │                            LOCAL_DOWN_S 熔断、_OPENER 直连绕过代理
│     ├─ prompt.py                 提示词组装（v9 结构）
│     ├─ prompt_v11.py             提示词组装（v11）
│     ├─ prompt_v12.py             提示词组装（v12）
│     ├─ persona.py                人设入口 + IDENT_TABLE 多账号身份表
│     ├─ persona_v11.py            人设文本 v11
│     ├─ persona_v12.py            人设文本 v12
│     ├─ rules.py                  出话规则层（该怎么说/能推到哪/不能碰什么）
│     ├─ brief.py                  她的简报（把档案压成几百字）
│     ├─ brief_v11.py / brief_v12.py   简报的历史版本
│     ├─ opener.py                 开场白生成
│     └─ gate.py                   ★ 硬闸：13 条拒绝规则（长度/红线/复读/零信息/
│                                   commit 问句/昼夜错配/站外导流）
│
├─ guard/                          ── 守护层：进程生命周期
│  ├─ __init__.py
│  ├─ daemon.py                    ★ 主循环 cycle() 七阶段、状态机、设备自愈三级、
│  │                               节流常量（MATCH_EVERY/WAKE_EVERY/ROUND_BUDGET...）
│  ├─ lock.py                      ★ 单实例锁：O_EXCL 原子创建、死锁接管(os.replace)、
│  │                               心跳 HEARTBEAT_S、step 阶段进度
│  └─ watchdog.py                  看门狗：HANG_S=900（必须 > ROUND_BUDGET=600）
│
├─ data/                           ── 数据层
│  ├─ __init__.py
│  ├─ imdb.py                      ★ 直读 App 明文 SQLite：open_account()、
│  │                               latest()、sessions_for_texts()、
│  │                               _assert_readonly() 只读硬约束、本地镜像合并
│  ├─ pending.py                   待回台账（自己记的，不写 App 库）
│  └─ watch.py                     数据库变更监听（urgent 信号）
│
├─ tools/                          ── 运维脚本（不参与主流程）
│  ├─ msg_probe.py                 消息探针：每 15s 查一次新消息，写到 logs/
│  ├─ devwatch.py                  设备存活守护：offline 自动 adb kill-server/connect/重建
│  ├─ watchdog_live.py             进程守护：daemon 不在就拉起
│  ├─ logrotate.py                 日志滚动
│  ├─ crash_alert.py               崩溃告警（扫描日志里的 Traceback）
│  ├─ cost_watch.py                模型 token 花费统计
│  ├─ daily_review.py              每日复盘报告
│  ├─ voice_check.py               语音链路自检
│  ├─ prepare_photos.py            照片进相册（发图前置：放 DCIM + touch + 广播）
│  ├─ do_start_daemon.ps1          启动 daemon（Windows）
│  ├─ start_daemon.ps1             同上（带自检）
│  ├─ restart_daemon.ps1           重启 daemon
│  ├─ rebuild_db_cache.ps1         重建数据库缓存
│  ├─ reg_ops_tasks.ps1            注册计划任务
│  └─ reg_probe.ps1                注册消息探针任务
│
├─ tests/                          ── 121 个探针 / 验收脚本
│  └─ t_*.py                       每个模块对应一个或多个验证脚本，例如：
│                                  t_device.py   设备连通
│                                  t_eyes.py     读屏
│                                  t_chatlist.py 会话列表解析
│                                  t_flow_dry.py 主链路干跑
│                                  t_dbcheck.py  数据库结构
│                                  t_casepack.py 案情包
│                                  ...
│                                  用法：python tests/t_xxx.py（多数会真的操作设备，注意）
│
└─ docs/                           ── 文档
   ├─ ARCHITECTURE.md              架构详解（分层/数据流/常量表/坑）
   ├─ 部署与运行.md                从零到跑起来 + 改代码铁律
   └─ 目录树.md                    本文件
```

---

## 按「我想做什么」定位文件

| 我想… | 去这里 |
|---|---|
| 改机器人说话的风格 | `brain/engine/persona*.py`、`brain/engine/rules.py` |
| 改提示词结构 | `brain/engine/prompt*.py`、`brain/engine/llm.py` |
| 加一条「不能发」的规则 | `brain/engine/gate.py` |
| 改回复长度 | `brain/engine/gate.py::MAX_CHARS` |
| 改回几条消息 | `brain/engine/__init__.py::MAX_N`、`brain/reply.py::target_n()` |
| 改该回谁 | `brain/pendingq.py::candidates()`（**只改这里**） |
| 改清理红点的策略 | `brain/clear.py` |
| 改匹配/开场白 | `brain/match.py`、`brain/engine/opener.py` |
| 改唤醒条件 | `brain/wake.py::plan()` |
| 改主循环顺序 | `guard/daemon.py::cycle()`（改前先读第 7 章「抢占铁律」） |
| 改节奏/间隔 | `guard/daemon.py` 顶部常量 |
| App 改版导致认不出页面 | `eyes/page.py::SIG`、`eyes/uitree.py::TAB_RES` |
| 列表行判不准 | `eyes/chatlist.py::ROW_MIN_H_RATIO` |
| 点击点不准 | `eyes/uitree.py::hit()`、`brain/act.py` |
| 设备老掉线 | `tools/devwatch.py`、`guard/daemon.py::_dev_rescue` |
| 换模型 | `config/model.env` + `brain/engine/llm.py` |
