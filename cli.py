#!/usr/bin/env python3
"""基金周涨幅榜 CLI — 每周获取精选场内 ETF 的周涨幅。

数据源: push2his.eastmoney.com 日 K 线（前复权）
策略: 每批 5 只，批次间停 3 秒，避免被限流
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml
import akshare as ak
import pandas as pd


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "themes.yaml"
DATA_DIR = ROOT / "data"
WEEKLY_DIR = DATA_DIR / "weekly"
LATEST_PATH = DATA_DIR / "latest.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BATCH_SIZE = 5       # 每批几只
BATCH_DELAY = 3       # 批次间隔（秒）


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
    """刚结束这周的周一 ~ 周日。"""
    today = datetime.now().date()
    # 找最近一个周五，往前推 4 天到周一
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    last_monday = last_friday - timedelta(days=4)
    last_sunday = last_friday + timedelta(days=2)
    return f"{last_monday} ~ {last_sunday}"


def get_trading_dates():
    """返回 (上周一, 上周五) 用于净值计算。"""
    today = datetime.now().date()
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    last_monday = last_friday - timedelta(days=4)
    return last_monday, last_friday


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


def get_secid(code: str) -> str:
    """ETF 代码 → secid（0=深交所, 1=上交所）。"""
    return f"0.{code}" if code.startswith("1") else f"1.{code}"


def fetch_one_etf_weekly(code: str, monday: str, friday: str, session: requests.Session):
    """日 K 线算周涨幅：周一收盘 → 周五收盘，前复权。

    日 K 线返回 OHLC（开/高/低/收），纯自己算，不依赖预计算字段。
    """
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101", "fqt": "1",
        "beg": monday, "end": friday,
        "secid": get_secid(code),
    }
    try:
        r = session.get(KLINE_URL, params=params, timeout=10)
        data = r.json()
        klines = data.get("data", {}).get("klines", [])
        if len(klines) < 2:
            return None
        mon_close = float(klines[0].split(",")[2])
        fri_close = float(klines[-1].split(",")[2])
        if mon_close == 0:
            return None
        return round((fri_close / mon_close - 1) * 100, 2)
    except Exception:
        return None


def fetch_all_weekly(codes: list, monday: str, friday: str) -> dict:
    """分批获取 ETF 周涨幅，每批 {BATCH_SIZE} 只，批次间停 {BATCH_DELAY}s。"""
    total = len(codes)
    results = {}
    failed = 0

    print(f"📡 正在用日K线获取 {total} 只 ETF 周涨幅 (每批{BATCH_SIZE}只, 间隔{BATCH_DELAY}s)...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })

    for i, code in enumerate(codes):
        ret = fetch_one_etf_weekly(code, monday, friday, session)
        if ret is not None:
            results[code] = ret
        else:
            failed += 1

        # 每批结束停一下
        if (i + 1) % BATCH_SIZE == 0 and (i + 1) < total:
            time.sleep(BATCH_DELAY)

        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"   进度: {i+1}/{total} (成功 {len(results)}, 失败 {failed})")

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
    last_monday, last_friday = get_trading_dates()

    print(f"📅 计算周期: {week_range}")
    print(f"   交易日: {last_monday}(周一) ~ {last_friday}(周五)")

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
        last_monday.strftime("%Y%m%d"),
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
