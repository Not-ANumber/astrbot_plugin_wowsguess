# Lesta 服数据包

本目录是 Lesta 服（RU 客户端，iwarship 的 `RU` 服务端）的瘦身数据包，结构与
[`packs/wg/`](../wg/) 完全一致：

- 数据源：`iwarship`，`sourceVersionId` 446
- 739 艘船、26 项属性、standard / hard 两套答案池（598 / 593 艘）
- 只包含舰船名、别名、拼音、稀有度、属性、答案池和 `groupOf`；
  不包含简介、舰船图、雷达图或任何游戏素材
- 与 WG 包同一套内容口径：IP 联动、Black Friday B 版、特殊换色版不进船表

数据由主数据仓库的 `npm run data:lesta` 生成，再经
`py scripts/export_bot_data.py --source <主仓库>/data/servers/lesta --server lesta`
导出。生成细节见主仓库 `data/README.md` 的「多服（Lesta）」一节。

## 与 WG 包的差异

- 船表不同：Lesta 有 200 余艘 WG 服没有的船，也缺少部分 WG 独占船。
- 没有出场排行快照，答案池的 `dailyPool` 直接等于 `answers`。
- 中文名优先来自 iwarship 详情页；缺口用社区汉化
  [LocalizedKorabli](https://github.com/LocalizedKorabli/Korabli-LESTA-L10N) 补齐，
  两种译名不一致时把另一个名字留作搜索别名。

## 授权

代码采用 MIT License，但**本目录的数据不在 MIT 许可范围内**。舰船名称、属性和
《战舰世界》相关内容归原数据提供方/权利人所有；再分发前请确认你拥有相应授权。

其中补缺的中文舰名来自 LocalizedKorabli 简体中文本地化，采用
**CC BY-NC-SA 4.0**（署名 · 非商业性使用 · 相同方式共享），署名
© 2023-2025 LocalizedKorabli（澪刻）。再分发包含这些名字的数据包时请保留署名与许可说明。
