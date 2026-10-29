# Lesta 数据包（暂未提供）

这里预留给 Lesta 服的数据包。当前仓库只有 WG/iwarship 数据管道，尚未产出 Lesta 的 `ships.json`、`attributes.json`、`difficulties.json` 和 `pools/`。

在数据准备好之前：

- 插件配置保持 `server: wg`；
- 或者把 `data_dir` 指向一个手动准备好的 Lesta 包目录；
- 选择 `server: lesta` 且没有数据时，插件会明确提示数据包缺失，不会回退到 WG。

Lesta 包的结构与 `packs/wg/` 完全一致，放入文件后即可使用；建议同时提供 `manifest.json`，并在其中写 `"server": "lesta"`。
