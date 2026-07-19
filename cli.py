#!/usr/bin/env python3
"""基金周涨幅榜 CLI — 每周获取精选场内 ETF 的净值周涨幅。

配置文件 config/themes.yaml 中维护每板块的固定 ETF 列表。
每周运行一次，通过 fund_etf_fund_info_em 获取净值计算周涨幅。
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml
import akshare as ak
import pandas as pd


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "themes.yaml"
DATA_DIR = ROOT / "data"
WEEKLY_DIR = DATA_DIR / "weekly"
LATEST_PATH = DATA_DIR / "latest.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"

REQUEST_DELAY = 0.2  # API 请求间隔


def load_config():
    """加载主题配置。"""
    if not CONFIG_PATH.exists():
        print(f"❌ 配置文件不存在: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ 配置文件解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    if config is None:
        print(f"❌ 配置文件为空: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    return config


def get_week_range() -> str:
    """上周一 ~ 上周日。"""
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return f"{last_monday} ~ {last_sunday}"


def fetch_etf_name_map() -> dict:
    """获取所有场内 ETF 代码 -> 名称的映射。"""
    print("📡 正在拉取场内 ETF 列表...")
    try:
        df = ak.fund_etf_spot_em()
    except Exception as e:
        print(f"❌ 获取 ETF 列表失败: {e}", file=sys.stderr)
        sys.exit(1)
    name_map = dict(zip(df["代码"].astype(str), df["名称"].astype(str)))
    print(f"   获取到 {len(name_map)} 只 ETF")
    return name_map


def fetch_one_nav_weekly(code: str, prev_friday: str, this_friday: str):
    """获取单只 ETF 上周的净值周涨幅。

    公式: (上周五单位净值 / 前周五单位净值 - 1) × 100
    """
    try:
        df = ak.fund_etf_fund_info_em(
            fund=code,
            start_date=prev_friday,
            end_date=this_friday,
        )
        if len(df) < 2:
            return None

        # 精确匹配前周五和上周五的净值
        prev_rows = df[df["净值日期"] == pd.Timestamp(
            f"{prev_friday[:4]}-{prev_friday[4:6]}-{prev_friday[6:]}")]
        this_rows = df[df["净值日期"] == pd.Timestamp(
            f"{this_friday[:4]}-{this_friday[4:6]}-{this_friday[6:]}")]

        if len(prev_rows) > 0 and len(this_rows) > 0:
            prev_nav = float(prev_rows.iloc[0]["单位净值"])
            this_nav = float(this_rows.iloc[0]["单位净值"])
        else:
            # 交易日不匹配时取首尾
            prev_nav = float(df.iloc[0]["单位净值"])
            this_nav = float(df.iloc[-1]["单位净值"])

        if prev_nav == 0:
            return None
        return round((this_nav / prev_nav - 1) * 100, 2)
    except Exception:
        return None


def fetch_all_weekly(codes: list, prev_friday: str, this_friday: str) -> dict:
    """获取一组 ETF 的周涨幅。

    Returns:
        {code: weeklyReturn}
    """
    total = len(codes)
    results = {}
    failed = 0

    print(f"📡 正在获取 {total} 只 ETF 的净值周涨幅...")
    for i, code in enumerate(codes):
        ret = fetch_one_nav_weekly(code, prev_friday, this_friday)
        if ret is not None:
            results[code] = ret
        else:
            failed += 1
        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"   进度: {i+1}/{total} (成功 {len(results)}, 失败 {failed})")
        time.sleep(REQUEST_DELAY)

    if failed:
        print(f"   ⚠️  {failed} 只 ETF 获取失败")
    return results


def build_result(config: dict, name_map: dict, weekly: dict, week_range: str) -> dict:
    """构建输出 JSON。"""
    themes_result = []
    for theme in config["themes"]:
        funds = []
        for code in theme["funds"]:
            if code in weekly:
                funds.append({
                    "code": code,
                    "name": name_map.get(code, code),
                    "weeklyReturn": weekly[code],
                    "type": "",
                })
        # 按周涨幅降序
        funds.sort(key=lambda x: x["weeklyReturn"], reverse=True)
        themes_result.append({
            "name": theme["name"],
            "funds": funds[:config["topN"]],
        })

    return {
        "week": week_range,
        "updatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "themes": themes_result,
    }


# ============================================================
# 数据保存
# ============================================================


def save_data(result: dict):
    """写入 JSON 文件。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)

    week_start = result["week"].split(" ~ ")[0]
    weekly_path = WEEKLY_DIR / f"{week_start}.json"
    content = json.dumps(result, ensure_ascii=False, indent=2)

    with open(weekly_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"💾 已保存: {weekly_path}")

    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"💾 已保存: {LATEST_PATH}")

    save_manifest()


def save_manifest():
    """生成 manifest.json。"""
    weeks = []
    for f in sorted(WEEKLY_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
                weeks.append({
                    "file": f.name,
                    "week": d.get("week", f.stem),
                    "updatedAt": d.get("updatedAt", ""),
                })
        except (json.JSONDecodeError, KeyError):
            continue

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump({"weeks": weeks}, f, ensure_ascii=False, indent=2)
    print(f"📋 已更新周索引: {len(weeks)} 周")


def git_commit_and_push():
    """提交并推送到 GitHub。"""
    try:
        subprocess.run(["git", "add", "data/"], check=True, cwd=ROOT)
        json_files = sorted(WEEKLY_DIR.glob("*.json"))
        if not json_files:
            return
        week_file = json_files[-1]
        subprocess.run(
            ["git", "commit", "-m", f"data: update fund weekly rank {week_file.stem}"],
            check=True, cwd=ROOT,
        )
        subprocess.run(["git", "push", "origin", "main"], check=True, cwd=ROOT)
        print("🚀 已推送到 GitHub")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git 操作失败: {e}", file=sys.stderr)
        print("   请手动执行: git add data/ && git commit && git push")


def print_summary(result: dict):
    """终端摘要。"""
    print(f"\n{'='*50}")
    print(f"📊 基金周涨幅榜 — {result['week']}")
    print(f"{'='*50}")
    for theme in result["themes"]:
        print(f"\n🏷️  {theme['name']}")
        print(f"   {'─'*30}")
        if not theme["funds"]:
            print("   (暂无匹配基金)")
            continue
        medals = ["🥇", "🥈", "🥉"]
        for i, fund in enumerate(theme["funds"]):
            prefix = medals[i] if i < 3 else f"  {i+1}."
            sign = "+" if fund["weeklyReturn"] >= 0 else ""
            print(f"   {prefix} {fund['code']} {fund['name']:<16s} {sign}{fund['weeklyReturn']:.2f}%")
    print(f"\n{'='*50}")


# ============================================================
# 主命令
# ============================================================


def cmd_update():
    """主命令：更新周涨幅数据。"""
    config = load_config()
    week_range = get_week_range()

    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    prev_friday = last_friday - timedelta(days=7)

    print(f"📅 计算周期: {week_range}")
    print(f"   交易日: {prev_friday} ~ {last_friday}")

    # 1. 收集所有 ETF 代码（去重）
    all_codes = list(dict.fromkeys(
        code for theme in config["themes"] for code in theme["funds"]
    ))
    print(f"📊 共 {len(config['themes'])} 个板块, {len(all_codes)} 只精选 ETF")

    # 2. 获取 ETF 名称映射
    name_map = fetch_etf_name_map()

    # 3. 获取净值周涨幅
    weekly = fetch_all_weekly(
        all_codes,
        prev_friday.strftime("%Y%m%d"),
        last_friday.strftime("%Y%m%d"),
    )

    # 4. 构建结果
    result = build_result(config, name_map, weekly, week_range)
    save_data(result)
    print_summary(result)

    # 确认推送
    answer = input("\n📤 是否 commit & push 到 GitHub? [Y/n]: ").strip().lower()
    if answer in ("", "y", "yes"):
        git_commit_and_push()
    else:
        print("⏭️  跳过推送，数据已本地保存")


def main():
    if len(sys.argv) < 2:
        print("用法: python cli.py update")
        sys.exit(1)

    if sys.argv[1] == "update":
        cmd_update()
    else:
        print(f"未知命令: {sys.argv[1]}")
        print("用法: python cli.py update")
        sys.exit(1)


if __name__ == "__main__":
    main()
