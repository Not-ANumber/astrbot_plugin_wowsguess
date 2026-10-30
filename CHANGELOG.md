# Changelog

## 未发布

- 新增 Lesta 服数据链路：主仓库 `npm run data:lesta` 从 iwarship `RU` 快照
  （versionId 446）生成 739 艘船的船表、26 项属性和两套答案池（598 / 593 艘），
  再经 `export_bot_data.py` 导出到 `packs/lesta/`。
- Lesta 舰名优先取 iwarship 详情页；缺口用社区汉化
  `LocalizedKorabli/Korabli-LESTA-L10N` 补齐（CC BY-NC-SA 4.0，署名写在数据包说明里），
  与详情页译名不一致时保留为搜索别名（36 艘）。
- Lesta 数据包随仓库和插件 ZIP 分发（`packs/lesta/`，约 0.45 MiB）；README 新增
  「数据包与数据版本」一节：用 `server` 选 wg / lesta，用 `manifest.json` 的
  `sourceVersionId` / `generatedAt` 确认版本，要用别的快照就外置包 + `data_dir`。
- `packs/lesta/README.md` 更新为实际数据说明、与 WG 包的差异和生成方式。
- 真实数据冒烟测试同时覆盖 WG 与 Lesta 包，缺包时自动跳过；新增答案池与 `groupOf` 不变量断言。
- 数据包缺失提示改为“随插件分发，缺失请重装或用 `data_dir`”，不再写“暂未提供”。
- 新增维护者脚本 `scripts/update_packs.py`：一条命令完成 iwarship 版本检查、两服构建、
  导出、单元测试和市场预检；`check_market.py` 增加两包 `attributes.json` /
  `difficulties.json` 一致性的断言，防止只更新一个包留下旧定义。

## 0.4.2 — 2026-10-29

- 公开 README 收敛为用户文档：安装、命令、配置、数据包、限制和许可；
  主数据源路径、导出命令、发布/打 tag、市场预检和字体子集等维护流程移到本地维护文档。
- `packs/README.md` 去掉仓库内部发布细节，只保留数据包格式和 Lesta 切换方式。
- 远程模式示例 token 改为 `<your-token>`，避免把示例值当生产值使用。

## 0.4.1 — 2026-10-29

- 内置 WG 官服数据包：`packs/wg/` 随仓库和插件 ZIP 分发，安装后默认 local 模式可直接玩；
  `packs/wg/README.md` 补数据来源、版本和授权边界。
- Lesta 数据默认留在仓库外：`packs/lesta/*.json` 继续被 `.gitignore` 忽略，切换步骤写入
  `packs/README.md`。
- 市场预检把“ZIP 内置 packs/wg”视为通过；`--strict` 不再因数据包缺失失败。
- README/metadata 更新为“内置 WG 包、Lesta 另放”的安装说明。

## 0.4.0 — 2026-10-29

- 核心对齐 Node/网页侧：
  - `close.bands` 分段绝对阈值（主炮口径、装填时间），按两值较大的绝对值选段；
  - 零值语义：0 与非 0 永远不判“接近”；
  - 新增对应测试，数据包声明 `bands` 后可正确解析。
- 数据包升级为分服结构：
  - `packs/wg/` 由 `scripts/export_bot_data.py` 生成，带 `manifest.json`（server、数据源、`generatedAt`、船数、文件 sha256）；
  - `packs/lesta/` 预留，当前数据包暂未提供；
  - 插件配置新增 `server`、`packs_dir`，按服使用独立数据库 `bot-<server>.sqlite`；
  - 0.3.x 的旧 `bot.sqlite` 在 WG 下自动复制为 `bot-wg.sqlite`。
- WG 包刷新到当前主仓库快照：784 艘、`generatedAt` 2026-10-24。
- 新增数据包解析/选择测试；本地真实数据测试改为读取 `packs/wg/`。
- 新增市场上架预检 `scripts/check_market.py`、GitHub Actions CI 和 256×256 `logo.png`；
  metadata 补 `social_link` / `tags`。

## 0.3.0 — 2026-10-24

- 同步当前官方开放平台侧的游戏语义改动：
  - `/统计`、`/战绩` 群战绩；
  - `/再来一局`、`/重开` 沿用上一局配置并跳过开局冷却；
  - 候选建议、`/1` 确认、`/取消` 放弃；
  - 模糊匹配/同长度错字自动纠正；
  - 统计表、玩家统计、最近答案避重、`stats_finalized` 幂等入账；
  - 官方 Markdown 快速菜单/帮助/候选/重开提示，OneBot 使用文本回退；
  - 结束后的快速重开追问；
  - 群白名单 `allowed_groups`。
- AstrBot 的公开消息链没有 keyboard 组件，官方按钮降级为 Markdown 内的命令提示。

## 0.2.1 — 2026-10-24

- 修复真实 AstrBot 以 `data.plugins.<dir>.main` 加载时，兄弟模块 `wowsguess_core.py` 无法相对导入的问题；改为 `wowsguess/remote.py` 包内模块。

## 0.2.0 — 2026-10-24

- 新增 **local 模式**：Python 游戏核心、SQLite 和 Pillow 渲染都在 AstrBot 进程内，
  零部署、无 HTTP 服务、无 token。
- 移植比对引擎、船名解析、命令分类、合作状态机、SQLite 仓储和文本回退。
- 新增 Pillow 棋盘/开局/帮助图渲染，随插件附带 Noto Sans CJK SC 子集字体。
- 保留 **remote 模式**，继续支持独立的 `wowsguess-coop` HTTP 服务。
- 新增瘦身数据导出脚本和字体子集脚本；数据包约 0.5 MiB。
- 测试覆盖核心、状态机、存储、AstrBot 映射、文本和图片渲染。

## 0.1.0 — 2026-10-24

- 初始版本：AstrBot 群消息 → wowsguess-coop HTTP 服务。
- 支持 `/窝一把`、`/ccb`、`/状态`、`/结束`、`/帮助`、`/船名`。
- 支持 `#`、`＃`、`！`、`!` 前缀，并在发送前归一化为 `/`。
- 文本和 base64 PNG 回复；图片失败时回退到服务端提供的文本棋盘。
- 群主/管理员角色尽力解析；房主始终可以结束。
- 服务不可用时默认静默，可配置每群 60 秒一次的提示。
- 纯标准库实现，无第三方 Python 依赖。
