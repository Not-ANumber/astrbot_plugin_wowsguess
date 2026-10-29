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
    README.md          # 暂无数据，占位
```

- `packs/wg/` 随插件分发；`packs/lesta/` 目前只有占位说明，数据需要自行放入。
- 运行时会优先读 AstrBot `plugin_data/astrbot_plugin_wowsguess/packs/<server>/`，不存在时
  回退到插件目录下的 `packs/<server>/`；也可以用 `packs_dir` 显式指定根目录。
- `manifest.json` 记录 `server`、数据源、`generatedAt`、船数和每个文件的 sha256。
- 每个服使用独立数据库：`bot-wg.sqlite` / `bot-lesta.sqlite`，统计和进行中的局不会混在一起。

## WG 包

`packs/wg/` 已内置，来源和授权说明见 [wg/README.md](wg/README.md)。数据更新由维护者
按 `manifest.json` 的规则重新生成；普通用户不需要自己导出。

## 切换到 Lesta

Lesta 数据准备好后，插件不需要改代码，按下面顺序切：

1. 准备一个与 `packs/wg/` 同结构的目录，`manifest.json` 里写 `"server": "lesta"`；
2. 放到以下任意一处：
   - `plugin_data/astrbot_plugin_wowsguess/packs/lesta/`（推荐，插件更新不会丢）；
   - 插件目录 `packs/lesta/`（随插件一起分发时使用）；
   - 任意目录，然后把插件配置的 `data_dir` 指向它；
3. 把插件配置的 `server` 改成 `lesta`；
4. 重载插件或重启 AstrBot。

切换后：

- 新局写入 `bot-lesta.sqlite`，WG 的 `bot-wg.sqlite` 原样保留；
- `/统计` 只显示当前服；切回 `server: wg` 就能继续看 WG 统计；
- 数据版本变化会中止该服进行中的局，这是既有行为；
- 当前 `server` 是插件级配置。如果同一个 AstrBot 实例要同时服务 WG 和 Lesta 的群，
  需要跑两个实例/容器；一个实例只能选一个服。

`packs/lesta/` 目前只有占位说明。在数据放进去之前，选择 `server: lesta` 会明确报
数据包缺失，不会静默回退到 WG。

## 手动数据目录

如果不想用 `packs/`，可以在插件配置里设置 `data_dir` 指向任意一个包目录；设置后 `server` 只用于数据库和清单校验，不再决定路径。
