#!/usr/bin/env python3
"""AstrBot 插件市场上架预检。

检查项分三类：

- FAIL：硬性阻塞，修好之前不要提审；
- WARN：不阻塞本地测试，但会影响市场体验或审核；
- PASS：当前满足。

用法：
    py scripts/check_market.py
    py scripts/check_market.py --strict   # WARN 也视为失败，发布前用
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SIZE_LIMIT = 16 * 1024 * 1024
REQUIRED_ROOT = ("main.py", "metadata.yaml", "_conf_schema.json", "requirements.txt")
FORBIDDEN_PREFIXES = ("data/", "bot-data/", "_tmp/", "__pycache__/", ".git/")
FORBIDDEN_SUFFIXES = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".sqlite3", ".pyc")


class Report:
    def __init__(self) -> None:
        self.passes: list[str] = []
        self.warns: list[str] = []
        self.fails: list[str] = []

    def ok(self, message: str) -> None:
        self.passes.append(message)

    def warn(self, message: str) -> None:
        self.warns.append(message)

    def fail(self, message: str) -> None:
        self.fails.append(message)

    def print(self) -> None:
        for message in self.passes:
            print(f"[PASS] {message}")
        for message in self.warns:
            print(f"[WARN] {message}")
        for message in self.fails:
            print(f"[FAIL] {message}")
        print(
            f"\n汇总：{len(self.passes)} PASS · {len(self.warns)} WARN · {len(self.fails)} FAIL",
        )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def metadata_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0] in " \t#":
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[match.group(1)] = value
    return fields


def check_metadata(report: Report) -> None:
    path = ROOT / "metadata.yaml"
    if not path.is_file():
        report.fail("metadata.yaml 不存在")
        return
    text = read_text(path)
    fields = metadata_fields(text)

    required = ("name", "display_name", "desc", "version", "author", "repo")
    missing = [key for key in required if not fields.get(key)]
    if missing:
        report.fail(f"metadata.yaml 缺少字段：{', '.join(missing)}")
    else:
        report.ok("metadata.yaml 必填字段齐全")

    name = fields.get("name", "")
    if not re.fullmatch(r"astrbot_plugin_[a-z0-9_]+", name):
        report.warn(
            "插件名建议使用 astrbot_plugin_ 前缀、全小写、只含字母数字下划线：" f"{name!r}",
        )
    else:
        report.ok(f"插件标识符合规范：{name}")

    author = fields.get("author", "")
    if "/" in author or not author:
        report.fail("metadata.author 必须非空且不能包含 /")
    else:
        report.ok(f"author 可用于 plugin_id：{author}/{name}")

    version = fields.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        report.fail(f"metadata.version 不是语义化版本：{version!r}")
    else:
        report.ok(f"版本号合法：{version}")

    repo = fields.get("repo", "")
    if "your-name" in repo or "<" in repo or not repo.startswith("https://github.com/"):
        report.warn(f"metadata.repo 还是占位或不是 GitHub 地址：{repo!r}")
    else:
        report.ok(f"repo 已填写：{repo}")

    astrbot_version = fields.get("astrbot_version", "")
    if astrbot_version and not re.match(r"^(>=|>|==|~=|!=|<=|<|\*)", astrbot_version):
        report.warn(f"astrbot_version 不是 PEP 440 约束：{astrbot_version!r}")

    if "description" in fields:
        report.fail("metadata.yaml 同时出现了 desc 和 description；只保留 desc")
    if "short_desc" not in fields:
        report.warn("建议补 short_desc，市场卡片会更好读")
    if "support_platforms" not in text:
        report.warn("建议声明 support_platforms")


def check_schema(report: Report) -> None:
    path = ROOT / "_conf_schema.json"
    if not path.is_file():
        report.fail("_conf_schema.json 不存在")
        return
    try:
        schema = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        report.fail(f"_conf_schema.json 不是合法 JSON：{exc}")
        return
    if not isinstance(schema, dict) or not schema:
        report.fail("_conf_schema.json 必须是非空 JSON 对象")
        return
    report.ok(f"_conf_schema.json 合法，共 {len(schema)} 个配置项")

    main_path = ROOT / "main.py"
    if main_path.is_file():
        used = set(re.findall(r"config\.get\(\s*[\"']([^\"']+)[\"']", read_text(main_path)))
        missing = sorted(used - set(schema))
        if missing:
            report.fail(f"main.py 读取了 schema 中不存在的配置：{', '.join(missing)}")
        else:
            report.ok("main.py 的配置项都能在 schema 中找到")


def check_requirements(report: Report) -> None:
    path = ROOT / "requirements.txt"
    if not path.is_file():
        report.fail("requirements.txt 不存在")
        return
    lines = [
        line.strip()
        for line in read_text(path).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        report.warn("requirements.txt 为空；如果确实没有依赖可以删除该文件")
    else:
        report.ok(f"requirements.txt 声明了 {len(lines)} 个依赖")
    if any(re.match(r"(?i)^requests(?:\s|$|[<>=])", line) for line in lines):
        report.warn("AstrBot reviewer 建议不要在插件里使用 requests，改用 httpx/aiohttp")


def check_main(report: Report) -> None:
    path = ROOT / "main.py"
    if not path.is_file():
        report.fail("main.py 不存在")
        return
    text = read_text(path)
    if "@register(" in text and "class " in text and "(Star)" in text:
        report.ok("main.py 使用 @register + Star 的标准插件结构")
    else:
        report.warn("main.py 未检测到 @register + Star 结构，确认能被 AstrBot 发现")
    if "asyncio.to_thread" in text or "async def" in text:
        report.ok("main.py 有异步入口")


def collect_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        files = []
        for line in result.stdout.splitlines():
            name = line.strip()
            if not name:
                continue
            path = ROOT / Path(name)
            if path.is_file():
                files.append(path)
        return files

    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            continue
        files.append(path)
    return files


def check_zip(report: Report) -> None:
    files = collect_files()
    if not files:
        report.fail("没有收集到可打包文件")
        return

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "plugin.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                rel = path.relative_to(ROOT).as_posix()
                bundle.write(path, rel)

        size = archive.stat().st_size
        if size > SIZE_LIMIT:
            report.fail(
                f"ZIP 体积 {size / 1024 / 1024:.2f} MiB 超过市场 16 MiB 限制",
            )
        else:
            report.ok(f"ZIP 体积 {size / 1024 / 1024:.2f} MiB，低于 16 MiB")

        names = set(bundle.namelist())
        missing = [name for name in REQUIRED_ROOT if name not in names]
        if missing:
            report.fail(f"ZIP 根目录缺少：{', '.join(missing)}")
        else:
            report.ok("ZIP 根目录包含 main.py / metadata.yaml / _conf_schema.json / requirements.txt")

        bad = []
        for name in names:
            if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                bad.append(name)
            elif name.endswith(FORBIDDEN_SUFFIXES):
                bad.append(name)
            elif name.endswith(".env") or "/.env" in name:
                bad.append(name)
        if bad:
            report.fail(f"ZIP 含有不应发布的文件：{', '.join(sorted(bad)[:8])}")
        else:
            report.ok("ZIP 未包含 data/、bot-data/、sqlite、缓存或 .env")

        pack_entries = [name for name in names if name.startswith("packs/") and name.endswith(".json")]
        wg_entries = [name for name in pack_entries if name.startswith("packs/wg/")]
        if "packs/wg/ships.json" in names:
            report.ok(
                f"ZIP 内置 WG 数据包（{len(wg_entries)} 个 JSON）；确认数据授权允许随插件分发",
            )
        else:
            report.warn(
                "ZIP 没有内置 packs/wg/ships.json；市场默认安装后本地模式还需要下载或手动放入",
            )
        lesta_entries = [name for name in pack_entries if name.startswith("packs/lesta/")]
        if "packs/lesta/ships.json" in names:
            report.ok(f"ZIP 内置 Lesta 数据包（{len(lesta_entries)} 个 JSON）")
        else:
            report.warn("ZIP 没有内置 packs/lesta/ships.json")

        if "logo.png" in names:
            report.ok("ZIP 包含 logo.png")
        else:
            report.warn("没有 logo.png；市场卡片会缺少图标")


def check_logo(report: Report) -> None:
    path = ROOT / "logo.png"
    if not path.is_file():
        report.warn("logo.png 不存在")
        return
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001 - Pillow is optional in this check
        report.warn(f"无法读取 logo.png 尺寸：{exc}")
        return
    if width != height:
        report.warn(f"logo.png 不是 1:1：{width}x{height}")
    else:
        report.ok(f"logo.png 是 1:1：{width}x{height}")


def check_pack(report: Report) -> None:
    packs = ROOT / "packs"
    wg = packs / "wg"
    if not (wg / "ships.json").is_file():
        report.warn(
            "packs/wg/ships.json 不存在；本地开发可先运行 "
            "py scripts/export_bot_data.py --source ../GTS/data --server wg",
        )
    else:
        report.ok("packs/wg 数据包存在")

    manifest_path = wg / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(read_text(manifest_path))
        except json.JSONDecodeError as exc:
            report.fail(f"packs/wg/manifest.json 不是合法 JSON：{exc}")
            manifest = None
        if isinstance(manifest, dict):
            if manifest.get("server") != "wg":
                report.fail(f"packs/wg 清单 server 不是 wg：{manifest.get('server')!r}")
            else:
                report.ok("packs/wg 清单 server=wg")
            files = manifest.get("files")
            if isinstance(files, dict):
                bad = []
                for rel, meta in files.items():
                    path = wg / rel
                    if not path.is_file():
                        bad.append(f"{rel} 缺失")
                        continue
                    raw = path.read_bytes()
                    if not isinstance(meta, dict):
                        bad.append(f"{rel} 元数据非法")
                    elif meta.get("size") != len(raw):
                        bad.append(f"{rel} size 不一致")
                    elif meta.get("sha256") != hashlib.sha256(raw).hexdigest():
                        bad.append(f"{rel} sha256 不一致")
                if bad:
                    report.fail(f"packs/wg 清单校验失败：{'; '.join(bad[:5])}")
                else:
                    report.ok(f"packs/wg 清单校验通过（{len(files)} 个文件）")
            else:
                report.warn("packs/wg/manifest.json 没有 files 表")
    else:
        report.warn("packs/wg/manifest.json 不存在；建议重新导出以生成校验清单")

    lesta = packs / "lesta"
    if not (lesta / "ships.json").is_file():
        report.warn(
            "packs/lesta/ships.json 不存在；随仓库分发时应存在，本地开发可运行 "
            "py scripts/export_bot_data.py --source ../GTS/data/servers/lesta --server lesta",
        )
    else:
        report.ok("packs/lesta 数据包存在")
        manifest_path = lesta / "manifest.json"
        if not manifest_path.is_file():
            report.warn("packs/lesta/manifest.json 不存在；重新导出以生成校验清单")
        else:
            try:
                manifest = json.loads(read_text(manifest_path))
            except json.JSONDecodeError as exc:
                report.fail(f"packs/lesta/manifest.json 不是合法 JSON：{exc}")
                manifest = None
            if isinstance(manifest, dict):
                if manifest.get("server") != "lesta":
                    report.fail(f"packs/lesta 清单 server 不是 lesta：{manifest.get('server')!r}")
                else:
                    report.ok("packs/lesta 清单 server=lesta")
                files = manifest.get("files")
                if isinstance(files, dict):
                    bad = []
                    for rel, meta in files.items():
                        path = lesta / rel
                        if not path.is_file():
                            bad.append(f"{rel} 缺失")
                            continue
                        raw = path.read_bytes()
                        if not isinstance(meta, dict):
                            bad.append(f"{rel} 元数据非法")
                        elif meta.get("size") != len(raw):
                            bad.append(f"{rel} size 不一致")
                        elif meta.get("sha256") != hashlib.sha256(raw).hexdigest():
                            bad.append(f"{rel} sha256 不一致")
                    if bad:
                        report.fail(f"packs/lesta 清单校验失败：{'; '.join(bad[:5])}")
                    else:
                        report.ok(f"packs/lesta 清单校验通过（{len(files)} 个文件）")
                else:
                    report.warn("packs/lesta/manifest.json 没有 files 表")

    # attributes / difficulties 是两个服共用的定义（导出时从主仓库 data/ 复制）。
    # 只更新一个包会留下旧定义，所以这里强制要求两个包一致。
    if (wg / "ships.json").is_file() and (lesta / "ships.json").is_file():
        for name in ("attributes.json", "difficulties.json"):
            try:
                wg_doc = json.loads(read_text(wg / name))
                lesta_doc = json.loads(read_text(lesta / name))
            except (OSError, json.JSONDecodeError) as exc:
                report.fail(f"两个包的 {name} 读取失败：{exc}")
                continue
            if wg_doc == lesta_doc:
                report.ok(f"两个包的 {name} 一致")
            else:
                report.fail(
                    f"两个包的 {name} 不一致；先重建 Lesta 包"
                    "（py scripts/update_packs.py --server lesta）",
                )


def check_repo(report: Report) -> None:
    try:
        remotes = subprocess.run(
            ["git", "-C", str(ROOT), "remote", "-v"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        remotes = ""
    if not remotes:
        report.warn("插件仓库还没有配置 git remote；市场安装需要公开仓库地址")
    else:
        report.ok("插件仓库已配置 git remote")

    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if status:
        report.warn("工作区有未提交改动；提审前先提交并打 tag")
    else:
        report.ok("工作区干净")

    tags = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "--points-at", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not tags:
        report.warn("当前 commit 没有 tag；发布时建议打 vX.Y.Z")
    else:
        report.ok(f"当前 commit 有 tag：{tags.splitlines()[0]}")

    if not (ROOT / ".github" / "workflows").is_dir():
        report.warn("没有 GitHub Actions 工作流；建议至少跑测试和本预检")
    else:
        report.ok("存在 GitHub Actions 工作流目录")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把 WARN 也视为失败，发布前使用",
    )
    args = parser.parse_args()

    report = Report()
    check_metadata(report)
    check_schema(report)
    check_requirements(report)
    check_main(report)
    check_zip(report)
    check_logo(report)
    check_pack(report)
    check_repo(report)
    report.print()

    if report.fails:
        print("\n结论：存在硬性阻塞，先处理 FAIL。")
        return 1
    if args.strict and report.warns:
        print("\n结论：--strict 下 WARN 也算失败。")
        return 1
    print("\n结论：没有硬性阻塞；WARN 项按发布目标决定是否处理。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
