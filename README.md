# 窝一把 · AstrBot 插件

把「窝一把」的 QQ 群合作猜船模式接进 [AstrBot](https://github.com/AstrBotDevs/AstrBot)。

全群共用一艘答案、共用 8 次机会，任何人可以猜；猜中即胜，次数用尽即负。
每次有效猜测返回一张棋盘图，答案只在结束时揭晓。

**默认 local 模式是零部署的**：游戏核心、SQLite、Pillow 渲染都在 AstrBot 进程内，
不需要 Docker、Node、端口或 token。插件内置 WG 官服和 Lesta 服两套数据包，装好即可玩。

## 两种模式

| 模式 | 需要什么 | 适合 |
|---|---|---|
| **local（默认）** | 插件（内置 `packs/wg` 与 `packs/lesta`） | 绝大多数 AstrBot 用户；无额外进程 |
| **remote** | 独立的 `wowsguess-coop` HTTP 服务 + 地址/token | 多机器人共享状态、已有服务、想集中运维 |

local 模式按配置的 `server` 选择数据包：默认 `wg`，优先读取 AstrBot
`plugin_data/astrbot_plugin_wowsguess/packs/<server>/`，没有时使用插件内置的
`packs/<server>/`。数据库按服分开，默认写到 AstrBot 的
`data/plugin_data/astrbot_plugin_wowsguess/bot-<server>.sqlite`。

## 安装

### 1. 安装插件

AstrBot WebUI → **插件** → **安装插件** → **从链接安装**，填本仓库地址：

```text
https://github.com/Not-ANumber/astrbot_plugin_wowsguess
```

也可以把仓库打成 ZIP，用 **从文件安装** 上传。ZIP 根目录必须直接包含
`main.py`、`metadata.yaml`、`_conf_schema.json` 和 `requirements.txt`。

AstrBot 会自动安装 `requirements.txt` 里的 Pillow。

### 2. 数据包与数据版本（local 模式）

插件内置两套数据包，**用配置项 `server` 选择用哪一套**：

| `server` | 数据包 | 数据源快照 | 舰船 | 答案池（普通 / 困难） |
|---|---|---|---|---|
| `wg`（默认） | `packs/wg/` | iwarship ASIA `versionId 435` | 784 | 604 / 595 |
| `lesta` | `packs/lesta/` | iwarship RU `versionId 446` | 739 | 598 / 593 |

设置位置：AstrBot WebUI → 插件配置 → `server` 选 `wg` 或 `lesta`，然后重载插件
或重启 AstrBot。两个服使用独立数据库（`bot-wg.sqlite` / `bot-lesta.sqlite`），
切换不会混统计，也不会丢掉另一服进行中的局。

**怎么确认当前用的是哪份数据版本：**

- 看 `packs/<server>/manifest.json`：`sourceVersionId` 是 iwarship 快照号，
  `generatedAt` 是生成时间，`shipCount` / `attributeCount` 是规模和属性数，
  `files` 里是每个文件的 `size` / `sha256`。
- 启动日志会打印一行包描述，例如 `WG 官服 · 784 艘 · 2026-10-24T…`。
- 数据版本变化会中止该服进行中的局——答案和属性不能跨版本继续，这是有意行为。

**想用别的数据版本：**

- 插件升级时，内置包会换成维护者打包时的快照，这是默认的“跟插件版本走”。
- 想钉住另一份快照、或用自己构建的数据包：把配置项 `data_dir` 指向一个完整包目录，
  此时 `server` 只用于选数据库和校验清单，不再决定路径。
- 不要直接修改插件目录里的 `packs/<server>/`：插件更新会覆盖它。外置包放到
  `plugin_data/astrbot_plugin_wowsguess/packs/<server>/`（推荐），或任意目录 + `data_dir`。

一个包目录的结构（两个服相同）：

```text
packs/<server>/
├─ manifest.json        # server、数据源、sourceVersionId、generatedAt、船数、文件 sha256
├─ ships.json
├─ attributes.json
├─ difficulties.json
└─ pools/
   ├─ standard.json
   └─ hard.json
```

两个包都随仓库和插件 ZIP 分发，不需要再导出。数据的来源、版本和授权说明分别在
[packs/wg/README.md](packs/wg/README.md) 和
[packs/lesta/README.md](packs/lesta/README.md)；数据不在 MIT 许可范围内，
再分发前请确认授权（Lesta 的中文舰名还有 CC BY-NC-SA 4.0 的署名要求）。

### 3. 直接玩

在群里 @机器人：

```text
@机器人 /窝一把
```

不需要填 URL、token 或数据库路径。插件自带中文字体子集，Linux/Docker 里也不会出现方框。

如果 `packs/<server>/` 不存在，插件不会静默失败：它会回一条“本地模式不可用”的提示，告诉你
缺哪个目录，或者切到 remote 模式。

## 命令

所有操作都在群里进行，推荐先 @机器人：

```text
@机器人 /窝一把 [n|h] [5-8]    开一局（默认普通 · 5–11）
@机器人 /ccb [n|h] [5-8]       同义写法
@机器人 /状态                   查看当前棋盘
@机器人 /统计                   查看本群战绩
@机器人 /结束                   房主/群管理员提前结束并揭晓
@机器人 /再来一局               结束后沿用上一局配置快速重开
@机器人 /帮助
@机器人 /秋月                   猜一次（消耗一次共享机会）
@机器人 /1 或 /取消             确认/放弃上一条候选
```

也支持 `#`、`＃`、`！`、`!` 前缀：

```text
@机器人 #窝一把 h 5-8
@机器人 #秋月
```

`/help` 固定留给 AstrBot，游戏帮助请用 `/帮助` 或 `#帮助`。

AstrBot 默认把 `/` 当作唤醒前缀，因此 `/状态` 这类命令即使没有 @机器人，也会被当成
显式命令处理；`#`/`！` 前缀则仍然要求 @机器人。

规则（由本地核心执行）：

- 全群共用 8 次机会，不需要加入，晚来的人直接猜；
- 一次有效猜测后全群冷却 3 秒，同一用户冷却 5 秒；
- 重复船、未知船名、冷却中、候选提示都不消耗次数；
- 支持拼音和同长度错字；近似船名先列候选，`/1` 确认；
- 先判是否猜中，再判次数是否用尽：第 8 猜猜中算赢；
- 结束后 `/再来一局` 沿用上一局难度/等级并跳过开局冷却；
- `/统计` 查看本群累计战绩、连胜和猜船榜；
- 同签名组（换皮船、同型舰）算猜中；
- 答案只在结束时出现，进行中的图片不含答案；
- 一局 2 小时无操作自动过期，结束后再开是新的一局。

## 配置

| 配置 | 默认 | 说明 |
|---|---|---|
| `mode` | `local` | `local` 进程内运行；`remote` 连接 HTTP 服务 |
| `server` | `wg` | `wg` 官服 / `lesta`；分别读取 `packs/<server>/` 并使用独立数据库 |
| `packs_dir` | 空 | 数据包根目录；空 = `plugin_data/astrbot_plugin_wowsguess/packs/`，不存在时回退插件目录 `packs/` |
| `data_dir` | 空 | 高级：直接指定单个数据包目录；空 = `packs_dir/<server>/` |
| `db_path` | 空 | 高级：直接指定 SQLite 路径；空 = AstrBot `plugin_data` 下的 `bot-<server>.sqlite` |
| `font_path` | 空 | local 模式中文字体；空 = 自带的 `NotoSansSC-subset.otf` |
| `allowed_groups` | 空 | 逗号分隔群白名单；NapCat 填群号，官方 QQ 填 `group_openid`；空 = 所有群 |
| `service_url` | `http://127.0.0.1:8787` | 仅 remote |
| `auth_token` | 空 | 仅 remote，与服务端一致 |
| `request_timeout` | `15` | 仅 remote，请求超时秒数 |
| `reserved_commands` | `help,model,new,...` | 留给 AstrBot 的 `/` 指令 |
| `notify_errors` | `false` | 仅 remote，服务不可用时是否提示 |

## local 模式细节

- 每个服使用独立数据库（`bot-wg.sqlite` / `bot-lesta.sqlite`），统计和进行中的局不会混。
- 数据版本变化时，进行中的旧局会自动中止，避免答案和属性漂移。
- **一个数据库只给一个 AstrBot 进程用**。local 模式没有多实例租约；两个进程同时写
  同一个数据库会让次数和冷却错乱。需要多实例请用 remote 模式。
- 备份对应服的 `bot-<server>.sqlite` 即可保留进行中的局；数据库里有答案，不要放进静态目录。
- 插件更新会替换代码目录，所以数据库放在 `plugin_data/`，不在插件代码目录里。

## remote 模式

remote 模式保留原来的 HTTP 协议：插件只做事件映射，答案、状态和渲染在一个独立的
`wowsguess-coop` 服务里。协议见 [docs/protocol.md](docs/protocol.md)。

> remote 协议 v1 目前只覆盖 `text` / `image` / `none`；`/统计`、`/再来一局`、候选确认
> 和官方 Markdown 是 local 核心的新能力，remote 服务尚未实现。需要这些功能请用 local。

```yaml
# 插件配置
mode: remote
service_url: http://wowsguess:8787
auth_token: "<your-token>"
```

同网络的 compose 模板见 [examples/docker-compose.example.yml](examples/docker-compose.example.yml)。
服务不在本仓库；remote 模式适合已经有服务或多机器人共享状态的场景。

## 开发与测试

```bash
# 单元测试（不需要 AstrBot）
py -m unittest discover -s tests -t . -v

# 语法检查
py -m py_compile main.py wowsguess/*.py wowsguess/render/*.py
```

测试覆盖核心比对规则、船名搜索、数据包解析、SQLite 仓储、合作状态机、AstrBot 事件映射和渲染。
已在 **AstrBot 4.29.1** 的真实 `PluginManager` 和 `AstrMessageEvent` 下验证加载与图片回复。

## 已知限制

- **只支持群聊**。私聊没有 `group_id`，插件会直接跳过。
- **两套数据包都随仓库分发**。`packs/wg/`（784 艘）和 `packs/lesta/`（739 艘）
  内置在仓库与 ZIP 中；数据授权与代码 MIT 许可分开，见各自的 README。
  想换用别的快照用 `data_dir`，不要改内置目录。
- **`/help` 不归游戏管**。游戏帮助用 `/帮助` 或 `#帮助`。
- **官方 Markdown 按钮降级**：AstrBot 公开消息链没有 keyboard 组件；插件会发
  Markdown 菜单，并把按钮对应的 `/命令` 附成一行文本提示，功能不受影响。
- **角色信息尽力而为**。OneBot 的 `sender.role` 和官方 QQ 的 `member_role` 会读取；
  房主永远可以结束，其他群管理是否可用取决于平台适配器。
- **local 模式单实例**。需要多实例/多机器人共享请用 remote。
- 渲染字体是 Noto Sans CJK SC 的子集，只覆盖舰名、属性、UI 文案和数字；不要在图片里
  动态渲染任意用户文本。

## 许可

代码采用 MIT License。字体是 Noto Sans CJK SC 的子集，按 SIL Open Font License 1.1
分发，见 [assets/fonts/LICENSE-NotoSansCJK.txt](assets/fonts/LICENSE-NotoSansCJK.txt)。
`packs/wg/` 的舰船数据不在 MIT 许可范围内，授权说明见
[packs/wg/README.md](packs/wg/README.md)。

《战舰世界》及相关舰船名称、数据归原权利人所有；本项目是非官方粉丝作品，与 Wargaming 无关。
