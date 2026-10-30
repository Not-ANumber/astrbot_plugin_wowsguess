#!/usr/bin/env python3
"""更新插件内置的 WG / Lesta 数据包（维护者用）。

一条命令跑完两个服的标准流程：

    iwarship 版本检查 → 主仓库构建 → 导出到 packs/<server>/ → 单元测试 → 市场预检

用法（在插件仓库根目录）：

    py scripts/update_packs.py                    # 两个服都更新
    py scripts/update_packs.py --server lesta     # 只更新一个服
    py scripts/update_packs.py --source E:/GTS    # 主仓库路径（默认 ../GTS）
    py scripts/update_packs.py --skip-fetch       # 用已有快照重建，不重新抓取
    py scripts/update_packs.py --dry-run          # 只打印将要执行的命令
    py scripts/update_packs.py --strict           # check_market 的 WARN 也当失败
    py scripts/update_packs.py --log my.log       # 指定日志路径

每次运行默认把完整输出（含子进程的构建 / 测试 / 预检输出）写到
logs/update-packs-<时间>.log；--no-log 可关闭。

版本检查：脚本读取 https://iwarship.net/wowsdb/index 页面里的 serverVersion
（ASIA → wg，RU → lesta），与主仓库 data/scripts/servers.mjs 比较。不一致时会停下，
提醒先改 versionId 再更新——否则会把旧快照重新构建一遍。站点不可达/被限速时只告警，
继续用 servers.mjs 里的版本（适合离线重建）。

脚本不负责发布：不升版本号、不写 CHANGELOG、不提交、不打 tag。
更新完成后按 MAINTAINER.local.md 的发布清单处理。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "GTS"
SERVERS = ("wg", "lesta")
IWARSHIP_INDEX = "https://iwarship.net/wowsdb/index"
IWARSHIP_SERVER = {"wg": "ASIA", "lesta": "RU"}
UA = "Mozilla/5.0 (compatible; wowsguess/0.1; personal fan project; update-packs)"


class UpdateError(RuntimeError):
    """流程中途失败；由 main 统一打印并返回非 0。"""


class Tee:
    """把写入同时送到控制台和日志文件。"""

    encoding = "utf-8"

    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._streams[0].fileno()


def configure_output() -> None:
    """行缓冲：把本脚本的输出和子进程输出按执行顺序交错，重定向到日志时也不会乱。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass


def open_log(path: Path | None) -> tuple[TextIO, Path] | None:
    """打开日志文件；默认 logs/update-packs-<时间>.log。失败时只告警，不阻断流程。"""
    target = path or ROOT / "logs" / f"update-packs-{datetime.now():%Y%m%d-%H%M%S}.log"
    try:
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = target.open("w", encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"[warn] 无法写日志文件（{exc}）；只在控制台输出")
        return None
    return handle, target


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def npm_command(script: str) -> list[str]:
    """Windows 上 npm 是 .cmd，需要经 cmd.exe 启动；POSIX 直接执行。"""
    if sys.platform == "win32":
        return ["cmd", "/c", "npm", "run", script]
    return ["npm", "run", script]


def run(cmd: list[str], *, cwd: Path, dry_run: bool) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in cmd)
    print(f"$ {printable}    (cwd={cwd})")
    if dry_run:
        return
    # 逐行转发子进程输出：控制台实时可见，同时经 Tee 写进日志。
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
    code = process.wait()
    if code != 0:
        raise UpdateError(f"命令失败（exit {code}）：{printable}")


def fetch_iwarship_versions(timeout: float = 30) -> dict[str, dict[str, Any]]:
    """读取 iwarship 首页内嵌的 serverVersion 表。"""
    request = urllib.request.Request(IWARSHIP_INDEX, headers={"user-agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", "replace")
    match = re.search(r"serverVersion\s*=\s*(\{.*?\})\s*;", html, re.S)
    if not match:
        raise UpdateError("首页里找不到 serverVersion（页面结构可能变了）")
    data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise UpdateError("serverVersion 不是对象")
    return data


def read_pipeline_versions(source: Path) -> dict[str, dict[str, Any]]:
    """通过 Node 读取主仓库 data/scripts/servers.mjs 的版本表。"""
    node = shutil.which("node")
    if not node:
        raise UpdateError("找不到 node；主仓库的数据管道需要 Node ≥ 23.6")
    servers_js = (source / "data" / "scripts" / "servers.mjs").resolve()
    if not servers_js.is_file():
        raise UpdateError(f"找不到 {servers_js}；--source 是否指向主仓库根目录？")
    code = (
        f"import({json.dumps(servers_js.as_uri())})"
        ".then(m => console.log(JSON.stringify(m.serverVersions())))"
    )
    result = subprocess.run(
        [node, "-e", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise UpdateError(f"读取 servers.mjs 失败：{result.stderr.strip() or result.stdout.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise UpdateError(f"servers.mjs 输出不是 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("servers.mjs 的 serverVersions() 不是对象")
    return data


def check_versions(source: Path, servers: tuple[str, ...], *, allow_stale: bool) -> dict[str, dict[str, Any]]:
    """对比 iwarship 当前版本与主仓库注册表，打印表格；不一致时中止。"""
    pipeline = read_pipeline_versions(source)

    try:
        remote = fetch_iwarship_versions()
    except (urllib.error.URLError, TimeoutError, UpdateError, json.JSONDecodeError) as exc:
        print(f"[warn] 无法检查 iwarship 版本（{exc}）；继续使用 servers.mjs 里的版本")
        remote = {}

    print("")
    print("=== 数据源版本 ===")
    print(f"{'server':6}  {'iwarship':9}  {'页面 versionId':14}  {'servers.mjs':11}  状态")
    mismatched: list[str] = []
    for server in servers:
        key = IWARSHIP_SERVER[server]
        local_version = pipeline.get(server, {}).get("versionId")
        row = remote.get(key) if remote else None
        if row is None:
            print(f"{server:6}  {key:9}  {'—':14}  {str(local_version):11}  未检查")
            continue
        remote_version = row.get("versionId")
        game_version = row.get("gameVersion", "?")
        if remote_version == local_version:
            status = "一致"
        else:
            status = "不一致"
            mismatched.append(
                f"{server}: 页面 {remote_version}（{game_version}） vs servers.mjs {local_version}",
            )
        print(
            f"{server:6}  {key:9}  {str(remote_version):14}  {str(local_version):11}  {status}",
        )

    if mismatched:
        print("")
        print("[stop] 数据源版本与主仓库不一致：")
        for line in mismatched:
            print(f"  - {line}")
        print("先改主仓库 data/scripts/servers.mjs 的 versionId（或确认要用旧快照后加 --allow-stale），")
        print("再重新运行本脚本。否则会把旧快照重新构建一遍。")
        if not allow_stale:
            raise SystemExit(2)
    print("")
    return pipeline


def build(server: str, source: Path, *, skip_fetch: bool, dry_run: bool) -> None:
    print(f"=== 构建 {server} ===")
    if server == "wg":
        scripts = ("data:build", "data:validate") if skip_fetch else ("data",)
    else:
        scripts = ("data:lesta:build",) if skip_fetch else ("data:lesta",)
    for script in scripts:
        run(npm_command(script), cwd=source, dry_run=dry_run)


def export(server: str, source: Path, *, dry_run: bool) -> None:
    print(f"=== 导出 {server} 数据包 ===")
    source_dir = source / "data" if server == "wg" else source / "data" / "servers" / server
    if not (source_dir / "ships.json").is_file():
        raise UpdateError(f"缺少 {source_dir / 'ships.json'}；构建步骤没有产出？")
    run(
        [
            sys.executable,
            "scripts/export_bot_data.py",
            "--source",
            str(source_dir),
            "--server",
            server,
        ],
        cwd=ROOT,
        dry_run=dry_run,
    )


def verify(*, strict: bool, dry_run: bool) -> None:
    print("=== 单元测试 ===")
    run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=ROOT,
        dry_run=dry_run,
    )
    print("=== 市场预检 ===")
    cmd = [sys.executable, "scripts/check_market.py"]
    if strict:
        cmd.append("--strict")
    run(cmd, cwd=ROOT, dry_run=dry_run)


def summarize(servers: tuple[str, ...], pipeline: dict[str, dict[str, Any]]) -> None:
    print("")
    print("=== 数据包摘要 ===")
    print(f"{'server':6}  {'sourceVersionId':15}  {'generatedAt':24}  {'舰船':5}  普通 / 困难")
    for server in servers:
        manifest_path = ROOT / "packs" / server / "manifest.json"
        if not manifest_path.is_file():
            print(f"{server:6}  缺少 manifest.json")
            continue
        manifest = read_json(manifest_path)
        pool_dir = manifest_path.parent / "pools"
        counts = []
        for key in ("standard", "hard"):
            path = pool_dir / f"{key}.json"
            counts.append(len(read_json(path).get("answers", [])) if path.is_file() else "—")
        expected = pipeline.get(server, {}).get("versionId")
        actual = manifest.get("sourceVersionId")
        note = "" if expected in (None, actual) else f"  [warn] 期望 {expected}"
        print(
            f"{server:6}  {str(actual):15}  {str(manifest.get('generatedAt')):24}  "
            f"{str(manifest.get('shipCount')):5}  {counts[0]} / {counts[1]}{note}",
        )
    print("")
    print("两包的 attributes.json / difficulties.json 一致性由 check_market.py 校验。")


def print_checklist(servers: tuple[str, ...]) -> None:
    print("")
    print("=== 还需要人工处理 ===")
    reports = []
    if "wg" in servers:
        reports.append("data/report.md")
    if "lesta" in servers:
        reports.append("data/servers/lesta/report.md")
    if reports:
        print(f"1. 看主仓库 {' 与 '.join(reports)} 的断言结果")
    else:
        print("1. 看主仓库的数据报告")
    print("2. 主仓库：按 AGENTS.md 提交 data/ 与脚本改动")
    print("3. 插件仓库：更新 CHANGELOG.md，同步 metadata.yaml 与 wowsguess/remote.py 的 PLUGIN_VERSION")
    print("4. 提交、打 tag、推送；发布前在干净工作区跑 py scripts/check_market.py --strict")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="更新 WG / Lesta 内置数据包")
    parser.add_argument(
        "--server",
        choices=(*SERVERS, "all"),
        default="all",
        help="要更新的服；默认 all",
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help=f"主仓库根目录；默认 {DEFAULT_SOURCE}",
    )
    parser.add_argument("--skip-fetch", action="store_true", help="不重新抓取，用已有快照重建")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不执行")
    parser.add_argument("--strict", action="store_true", help="check_market 的 WARN 也当失败")
    parser.add_argument("--skip-version-check", action="store_true", help="跳过 iwarship 版本对比")
    parser.add_argument("--allow-stale", action="store_true", help="版本不一致也继续（显式确认）")
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "--log",
        default=None,
        help="日志文件路径；默认 logs/update-packs-<时间>.log",
    )
    log_group.add_argument("--no-log", action="store_true", help="不写日志文件")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_output()
    args = parse_args(argv)
    servers = SERVERS if args.server == "all" else (args.server,)
    source = Path(args.source).expanduser().resolve()

    if not (source / "package.json").is_file() or not (source / "data" / "scripts" / "build.mjs").is_file():
        print(f"[fail] --source 不是主仓库根目录：{source}", file=sys.stderr)
        return 1

    log = None if args.no_log else open_log(Path(args.log) if args.log else None)
    original_out, original_err = sys.stdout, sys.stderr
    if log:
        handle, path = log
        sys.stdout = Tee(original_out, handle)
        sys.stderr = Tee(original_err, handle)

    exit_code = 0
    try:
        print(f"# update_packs {datetime.now().isoformat(timespec='seconds')}")
        print(f"# python {sys.version.split()[0]}  platform {sys.platform}")
        print(f"# source {source}")
        print(
            f"# servers {', '.join(servers)}  skip_fetch={args.skip_fetch}  "
            f"strict={args.strict}  dry_run={args.dry_run}",
        )
        if log:
            print(f"[log] {log[1]}")

        if args.skip_version_check:
            pipeline = read_pipeline_versions(source)
            print("=== 数据源版本 ===")
            print("[skip] --skip-version-check；使用 servers.mjs 里的版本")
        else:
            pipeline = check_versions(source, servers, allow_stale=args.allow_stale)

        for server in servers:
            build(server, source, skip_fetch=args.skip_fetch, dry_run=args.dry_run)
            export(server, source, dry_run=args.dry_run)

        verify(strict=args.strict, dry_run=args.dry_run)
        summarize(servers, pipeline)
        print_checklist(servers)
    except UpdateError as exc:
        print(f"\n[fail] {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if log:
            sys.stdout = original_out
            sys.stderr = original_err
            log[0].close()
            print(f"[log] 已写入 {log[1]}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
