#!/usr/bin/env python3
"""基金周涨幅榜 CLI — 场内 ETF 周涨幅排行。

数据来源：东方财富 K 线 API (push2his.eastmoney.com)，
直接获取每只 ETF 的前复权周涨幅，不使用联接基金。
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

REQUEST_DELAY = 0.3  # 请求间隔，避免被限流


def load_config():
    """加载主题配置文件。"""
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
    """计算上周一～上周日的日期范围字符串。"""
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return f"{last_monday} ~ {last_sunday}"


# ============================================================
# 数据获取
# ============================================================


def fetch_etf_spot() -> pd.DataFrame:
    """获取场内 ETF 列表。"""
    print("📡 正在拉取场内 ETF 列表...")
    try:
        df = ak.fund_etf_spot_em()
    except Exception as e:
        print(f"❌ 获取 ETF 列表失败: {e}", file=sys.stderr)
        sys.exit(1)
    df = df[["代码", "名称"]].copy()
    df.columns = ["code", "name"]
    print(f"   获取到 {len(df)} 只场内 ETF")
    return df


def fetch_one_etf_weekly(code: str, prev_friday: str, this_friday: str):
    """获取单只 ETF 上周的净值周涨幅。

    通过 fund_etf_fund_info_em 获取历史净值，用前周五和上周五的
    单位净值计算周涨幅：(上周五净值 / 前周五净值 - 1) * 100。

    API 域名: api.fund.eastmoney.com（稳定，无限流问题）
    """
    try:
        df = ak.fund_etf_fund_info_em(
            fund=code,
            start_date=prev_friday,
            end_date=this_friday,
        )
        if len(df) < 2:
            return None

        prev_rows = df[df["净值日期"] == pd.Timestamp(prev_friday[:4] + "-" + prev_friday[4:6] + "-" + prev_friday[6:])]
        this_rows = df[df["净值日期"] == pd.Timestamp(this_friday[:4] + "-" + this_friday[4:6] + "-" + this_friday[6:])]

        if len(prev_rows) == 0 or len(this_rows) == 0:
            # 可能那两天不是交易日，取第一条和最后一条
            prev_nav = float(df.iloc[0]["单位净值"])
            this_nav = float(df.iloc[-1]["单位净值"])
        else:
            prev_nav = float(prev_rows.iloc[0]["单位净值"])
            this_nav = float(this_rows.iloc[0]["单位净值"])

        if prev_nav == 0:
            return None
        return (this_nav / prev_nav - 1) * 100
    except Exception:
        return None


def fetch_all_etf_weekly(etf_df: pd.DataFrame, prev_friday: str, this_friday: str) -> dict:
    """顺序获取所有匹配 ETF 的周涨幅。

    Returns:
        {code: {"weeklyReturn": float, "name": str}}
    """
    codes = etf_df["code"].tolist()
    total = len(codes)
    results = {}
    failed = 0

    print(f"📡 正在获取 {total} 只 ETF 的净值周涨幅（间隔 {REQUEST_DELAY}s）...")

    for i, code in enumerate(codes):
        weekly = fetch_one_etf_weekly(code, prev_friday, this_friday)
        name = str(etf_df[etf_df["code"] == code]["name"].values[0])
        if weekly is not None:
            results[code] = {"weeklyReturn": weekly, "name": name}
        else:
            failed += 1

        if (i + 1) % 100 == 0 or (i + 1) == total:
            print(f"   进度: {i+1}/{total} (成功 {len(results)}, 失败 {failed})")

        time.sleep(REQUEST_DELAY)

    if failed:
        print(f"   ⚠️  {failed} 只 ETF 获取失败")
    return results

    print(f"📡 正在获取 {total} 只 ETF 的周涨幅（间隔 {REQUEST_DELAY}s）...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    })

    for i, code in enumerate(codes):
        weekly = fetch_one_etf_weekly(code, monday, friday, session)
        name = str(etf_df[etf_df["code"] == code]["name"].values[0])
        if weekly is not None:
            results[code] = {"weeklyReturn": weekly, "name": name}
        else:
            failed += 1

        if (i + 1) % 100 == 0 or (i + 1) == total:
            print(f"   进度: {i+1}/{total} (成功 {len(results)}, 失败 {failed})")

        time.sleep(REQUEST_DELAY)

    if failed:
        print(f"   ⚠️  {failed} 只 ETF 获取失败")
    return results


def fetch_fund_type_map() -> dict:
    """获取基金代码 → 基金类型的映射。"""
    print("📡 正在拉取基金类型数据...")
    try:
        df = ak.fund_name_em()
    except Exception as e:
        print(f"❌ 获取基金类型数据失败: {e}", file=sys.stderr)
        sys.exit(1)
    df = df.dropna(subset=["基金代码"])
    type_map = dict(zip(df["基金代码"].astype(str), df["基金类型"].astype(str)))
    print(f"   获取到 {len(type_map)} 只基金的类型信息")
    return type_map


# ============================================================
# 主题分类
# ============================================================


def classify_etfs(etf_data: dict, themes: list) -> dict:
    """按主题关键词将 ETF 归类。"""
    classified = {}

    for theme in themes:
        theme_name = theme["name"]
        pattern = "|".join(theme["keywords"])
        funds = []
        for code, info in etf_data.items():
            name = info["name"]
            if any(kw in name for kw in theme["keywords"]):
                funds.append({
                    "code": code,
                    "name": name,
                    "weeklyReturn": info["weeklyReturn"],
                    "type": "",
                })

        # 按周涨幅降序
        funds.sort(key=lambda x: x["weeklyReturn"], reverse=True)
        classified[theme_name] = funds
        print(f"   {theme_name}: {len(funds)} 只")

    return classified


def build_result(classified: dict, top_n: int, week_range: str) -> dict:
    """构建输出 JSON。"""
    themes_result = []
    for theme_name, funds in classified.items():
        seen = set()
        unique = []
        for f in funds:
            if f["code"] not in seen:
                seen.add(f["code"])
                unique.append(f)
        themes_result.append({"name": theme_name, "funds": unique[:top_n]})

    return {
        "week": week_range,
        "updatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "themes": themes_result,
    }


# ============================================================
# 数据保存
# ============================================================


def save_data(result: dict):
    """写入 data/weekly/ 和 data/latest.json。"""
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
            print("⚠️  没有找到周数据文件，跳过 commit", file=sys.stderr)
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
    """在终端打印本周摘要。"""
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
    print(f"   交易日: {prev_friday}(前周五) ~ {last_friday}(上周五)")

    # 1. 拉取 ETF 列表
    etf_df = fetch_etf_spot()

    # 2. 预筛选：匹配任意主题关键词的 ETF
    all_keywords = set()
    for theme in config["themes"]:
        for kw in theme["keywords"]:
            all_keywords.add(kw)
    pattern = "|".join(all_keywords)
    mask = etf_df["name"].str.contains(pattern, na=False)
    matched_df = etf_df[mask].copy()
    print(f"🔍 关键词预筛选: {len(matched_df)} / {len(etf_df)} 只 ETF 匹配")

    # 3. 获取每只 ETF 的周涨幅（净值法：前周五净值 → 上周五净值）
    etf_data = fetch_all_etf_weekly(
        matched_df,
        prev_friday.strftime("%Y%m%d"),
        last_friday.strftime("%Y%m%d"),
    )

    # 4. 按主题分类
    print("🔍 正在按主题归类...")
    classified = classify_etfs(etf_data, config["themes"])
    result = build_result(classified, config["topN"], week_range)
    save_data(result)
    print_summary(result)

    # 确认是否推送
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
