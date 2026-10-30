# 数据包

插件按 `server` 选择数据包，每个包是自包含目录：

```text
packs/
  wg/
    manifest.json
    ships.json
    attributes.json
    difficulties.json
    pools/
      standard.json
      hard.json
  lesta/
    manifest.json
    ships.json
    attributes.json
    difficulties.json
    pools/
      standard.json
      hard.json
```

- `packs/wg/` 和 `packs/lesta/` 都随插件分发，安装后直接可用。
- 运行时会优先读 AstrBot `plugin_data/astrbot_plugin_wowsguess/packs/<server>/`，不存在时
  回退到插件目录下的 `packs/<server>/`；也可以用 `packs_dir` 显式指定根目录。
- `manifest.json` 记录 `server`、数据源、`sourceVersionId`、`generatedAt`、船数和每个文件的 sha256。
- 每个服使用独立数据库：`bot-wg.sqlite` / `bot-lesta.sqlite`，统计和进行中的局不会混在一起。
- 内置包跟着插件版本走；想钉住别的快照，用外置包 + `packs_dir` / `data_dir`，
  不要修改内置目录（插件更新会覆盖）。
- 维护者更新两个包：`py scripts/update_packs.py`（`--help` 看参数）。两个包共用
  `attributes.json` / `difficulties.json`，`check_market.py` 会检查它们完全一致；
  每次运行的完整输出写在 `logs/update-packs-<时间>.log`（`logs/` 和 `*.log` 不进 ZIP）。

## WG 包

`packs/wg/` 已内置，来源和授权说明见 [wg/README.md](wg/README.md)。数据更新由维护者
按 `manifest.json` 的规则重新生成；普通用户不需要自己导出。

## Lesta 包

`packs/lesta/` 是 Lesta 服（iwarship `RU`，versionId 446）的瘦身包，船表与 WG 不同，
已随插件分发，来源、中文名和授权说明见 [lesta/README.md](lesta/README.md)。

两套包的数据版本互相独立：看各自的 `manifest.json` 的 `sourceVersionId` /
`generatedAt`，插件启动日志也会打印当前包的船数和生成时间。切换 `server` 不会改动
另一服的包或数据库。

## 切换到 Lesta

Lesta 包已内置，插件不需要改代码，按下面顺序切：

1. 把插件配置的 `server` 改成 `lesta`；
2. 重载插件或重启 AstrBot。

如果用的是外置或自定义 Lesta 包，先把它放到以下任意一处，再执行上面两步：

- `plugin_data/astrbot_plugin_wowsguess/packs/lesta/`（推荐，插件更新不会丢）；
- 任意目录，然后把插件配置的 `data_dir` 指向它。

切换后：

- 新局写入 `bot-lesta.sqlite`，WG 的 `bot-wg.sqlite` 原样保留；
- `/统计` 只显示当前服；切回 `server: wg` 就能继续看 WG 统计；
- 数据版本变化会中止该服进行中的局，这是既有行为；
- 当前 `server` 是插件级配置。如果同一个 AstrBot 实例要同时服务 WG 和 Lesta 的群，
  需要跑两个实例/容器；一个实例只能选一个服。

外置包缺失或清单里的 `server` 对不上时，插件会明确报数据包缺失/不匹配，
不会静默回退到 WG。

## 手动数据目录

如果不想用 `packs/`，可以在插件配置里设置 `data_dir` 指向任意一个包目录；设置后 `server` 只用于数据库和清单校验，不再决定路径。
