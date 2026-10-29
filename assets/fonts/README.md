# 中文字体

`NotoSansSC-subset.otf` 是从 **Noto Sans CJK SC Regular** 生成的字形子集，只保留：

- 全部舰船名（`name` / `nameZh` / `aliasZh`）；
- 属性标签、单位、枚举值；
- 棋盘、开局卡、帮助卡的 UI 文案、数字和标点。

这样插件可以随包携带字体，在 Windows、Linux、Docker、ARM NAS 上渲染结果一致，不依赖宿主机字体。

来源：<https://github.com/notofonts/noto-cjk> 的 `Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf`。

许可证：SIL Open Font License 1.1，见 [LICENSE-NotoSansCJK.txt](LICENSE-NotoSansCJK.txt)。字体文件本身可以随本项目分发；修改后的子集也按 OFL 分发。

重新生成（数据或 UI 文案变化后）：

```bash
py scripts/subset_font.py --source /path/to/NotoSansCJKsc-Regular.otf
```

`scripts/subset_font.py` 会从 `data/` 和源码里收集实际用到的字符，再调用 `fontTools.subset`。
