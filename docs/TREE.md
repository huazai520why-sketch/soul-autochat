# 目录树

> 2026-11-14 副机生产目录实测。当前 HEAD `bc50b70`。
> 当前约 105 个 Python 文件、2.38 万行、1.20 MB。完整生产拓扑见 [PROJECT_MAP.md](PROJECT_MAP.md)。

```text
soul-autochat/
├─ run.py                          ★ 唯一入口：check/screen/once/daemon/watchdog/wake/match/clear/pending/bell
├─ requirements.txt                依赖清单
├─ LICENSE                         MIT
├─ README.md                       项目总览
│
├─ config/
│  ├─ model.env.example            ✅ 配置模板（进仓库）
│  └─ model.env                    ❌ 真实配置（gitignore）
│
├─ core/                           设备层
│  ├─ __init__.py
│  ├─ device.py                    adb/root/u2、动作代数、慢设备因子、设备探测
│  ├─ paths.py                     路径、包名、分辨率、底栏文案、MuMu 路径
│  ├─ log.py                       按模块写日志、UTF-8 stdout、轮转
│  ├─ metrics.py                   JSONL 结构化指标
│  └─ message_kind.py              纯消息分类（human/system/ad）
│
├─ eyes/                           感知层（只读）
│  ├─ __init__.py
│  ├─ uitree.py                    UI 树 dump、节点定位、页面指纹
│  ├─ page.py                      7 类页面识别、底栏角标
│  ├─ chatlist.py                  会话列表解析、行高双闸、红点判断
│  ├─ chat.py                      气泡读取与左右归属
│  ├─ profile.py                   主页资料抓取
│  ├─ popup.py                     弹窗识别
│  ├─ ocr.py                       RapidOCR 封装
│  └─ sysmsg.py                    系统消息解析（历史架构中存在 data.imdb 反向捷径）
│
├─ hands/                          动作层（只动）
│  ├─ __init__.py
│  ├─ tap.py                       统一点击入口，动作前作废帧缓存
│  ├─ input.py                     灌字、发送、ok/unknown/residual 三态确认
│  └─ pic.py                       发图片
│
├─ brain/                          决策层
│  ├─ __init__.py
│  ├─ act.py                       Actor：帧复用、动作后强制刷新
│  ├─ nav.py                       导航升级梯子、回主界面、重启 App
│  ├─ flow.py                      ★ 进会话 → 判定 → 出话 → 发送
│  ├─ clear.py                     清红点
│  ├─ pendingq.py                  ★ 唯一待回候选判据
│  ├─ pending_policy.py            纯候选排序/冷却策略
│  ├─ reply.py                     出话编排、条数、兜底话术
│  ├─ match.py                     星球匹配与开场白
│  ├─ match_runner.py              `run.py match` 的生产运行器
│  ├─ wake.py                      沉默老友唤醒
│  ├─ bell.py                      奇遇铃、稍后再聊、跨轮去重
│  ├─ search.py                    搜索定位与熔断
│  ├─ voice.py / asr.py            语音消息转写
│  ├─ acct.py                      多账号轮转
│  ├─ casepack.py                  画像/案情包
│  ├─ ratelimit.py                 发送配额
│  ├─ scheduler.py                 时段策略
│  ├─ env.py                       环境探测
│  ├─ localq.py / picreq.py        本地队列、发图判断
│  ├─ sendgate.py                  发送闸门与归档
│  ├─ verdict.py                   回复判定
│  ├─ skills.py                    画像/策略/人性技能
│  ├─ stage.py                     关系阶段
│  ├─ pack/
│  │  ├─ __init__.py
│  │  └─ store.py                  v3 案情包存储
│  └─ engine/
│     ├─ __init__.py               respond() 统一出口、批内去重、冷档硬约束
│     ├─ llm.py                    方舟/Ollama、超时、熔断
│     ├─ prompt.py                 v9 提示词组装
│     ├─ persona.py                人设与多账号身份
│     ├─ rules.py                  出话规则
│     ├─ brief.py                  她的简报
│     ├─ opener.py                 开场白
│     └─ gate.py                   硬闸
│
├─ data/                           数据层
│  ├─ __init__.py
│  ├─ imdb.py                      直读 App SQLite、缩水保护、镜像合并
│  ├─ pending.py                   待回台账（当前反向依赖 brain 三个判据模块）
│  ├─ reply_state.py               回复状态
│  ├─ pending_ledger.py            共享冷却/已回台账
│  └─ watch.py                     数据库变更监听
│
├─ guard/                          守护层
│  ├─ __init__.py
│  ├─ daemon.py                    ★ 七阶段主循环、设备三级自愈
│  ├─ lock.py                      单实例锁、心跳、step 进度
│  └─ watchdog.py                  锁优先判活、统一走 start_daemon.ps1
│
├─ tools/                          运维与任务入口
│  ├─ silent_launch.py             ★ 所有 Soul 计划任务统一静默启动
│  ├─ _silent/
│  │  ├─ sitecustomize.py          子进程无窗口注入（禁止删除）
│  │  └─ win_audit.py              静默启动辅助审计
│  ├─ watchdog_live.py             daemon/MuMu 存活兜底
│  ├─ msg_probe.py                 每 15 秒消息新鲜度探针
│  ├─ devwatch.py                  设备离线恢复
│  ├─ logrotate.py                 日志轮转
│  ├─ crash_alert.py               Traceback 扫描告警
│  ├─ cost_watch.py                模型成本统计
│  ├─ daily_review.py              每日复盘
│  ├─ voice_check.py               语音链路自检
│  ├─ action_audit.py              动作审计
│  ├─ prepare_photos.py            相册准备
│  ├─ start_daemon.ps1             daemon 启动
│  ├─ restart_daemon.ps1           daemon 重启
│  ├─ do_start_daemon.ps1          兼容启动
│  ├─ rebuild_db_cache.ps1         数据库缓存重建
│  ├─ reg_ops_tasks.ps1            注册运维任务
│  └─ reg_probe.ps1               注册消息探针
│
├─ tests/                          26 个保留验收/回放与离线测试
│  ├─ _nolog.py
│  ├─ t_device.py / t_eyes.py / t_chatlist.py
│  ├─ t_dbcheck.py / t_casepack.py / t_flow_dry.py
│  ├─ t_preflight.py / t_run_loop.py / t_match_loop.py
│  ├─ t_bell_logic.py / t_outtalk_contract.py
│  ├─ t_act_warn_level.py / t_flow_fail_level.py
│  ├─ t_kw_masked_phone.py / t_followup_replay.py
│  ├─ t_nav_ladder.py / t_skills_replay.py
│  ├─ t_prompt_dump.py / t_wake_plan.py
│  ├─ t_flow_preempt.py / t_health_contract.py
│  ├─ t_lock_health.py / t_metrics.py
│  ├─ t_pending_ledger.py / t_pending_policy.py
│  └─ 说明：t_match_loop.py 现仅包装生产模块 brain.match_runner
│
├─ scripts/
│  └─ repo_sync.ps1                Git 漂移检查、脱敏扫描
│
└─ docs/
   ├─ ARCHITECTURE.md              架构详解
   ├─ DEPLOY.md                    部署与运行
   ├─ PROJECT_MAP.md               当前生产架构图与任务拓扑
   └─ TREE.md                      本文件
```

运行时数据不在 Git：`logs/`、`memory/`、`models/`、`data/state/`、`config/model.env`、密钥与 App 数据库镜像均应保留或单独备份，不属于孤儿文件。

---

## 按“我想做什么”定位文件

| 我想… | 去这里 |
|---|---|
| 改机器人说话风格 | `brain/engine/persona.py`、`brain/engine/rules.py` |
| 改提示词结构 | `brain/engine/prompt.py`、`brain/engine/llm.py` |
| 加不能发的规则 | `brain/engine/gate.py` |
| 改回复长度 | `brain/engine/gate.py::MAX_CHARS` |
| 改回几条消息 | `brain/engine/__init__.py::MAX_N`、`brain/reply.py::target_n()` |
| 改该回谁 | `brain/pendingq.py::candidates()` |
| 改清红点 | `brain/clear.py` |
| 改奇遇铃 | `brain/bell.py` |
| 改匹配/开场白 | `brain/match.py`、`brain/engine/opener.py` |
| 改唤醒条件 | `brain/wake.py::plan()` |
| 改主循环顺序 | `guard/daemon.py::cycle()` |
| 改计划任务启动 | `tools/silent_launch.py`、`tools/start_daemon.ps1` |
| App 改版认不出页面 | `eyes/page.py::SIG`、`eyes/uitree.py::TAB_RES` |
| 列表行判不准 | `eyes/chatlist.py::ROW_MIN_H_RATIO` |
| 点击点不准 | `eyes/uitree.py::hit()`、`brain/act.py` |
| 设备老掉线 | `tools/devwatch.py`、`guard/daemon.py::_dev_rescue` |
| 换模型 | `config/model.env`、`brain/engine/llm.py` |
