#!/usr/bin/env python3
"""基金周涨幅榜 CLI — 从 AKShare 拉取数据，生成 JSON 并推送。"""

import json
import subprocess
import sys
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


def fetch_fund_data() -> pd.DataFrame:
    """通过 AKShare 获取全市场开放式基金排行数据（含近1周涨幅）。

    注：东方财富 API 不支持按基金名称搜索，必须拉全量 ~20,000 只基金，
    然后在本地用向量化匹配筛选。API 单次请求约 4 秒，周末跑一次完全可接受。
    """
    print("📡 正在从东方财富拉取全市场基金排行数据...")
    try:
        df = ak.fund_open_fund_rank_em(symbol="全部")
    except Exception as e:
        print(f"❌ 获取基金排行数据失败: {e}", file=sys.stderr)
        print("   请检查网络连接或确认 AKShare 是否已正确安装", file=sys.stderr)
        sys.exit(1)
    print(f"   获取到 {len(df)} 只基金")

    if "近1周" not in df.columns:
        print('❌ 数据中缺少"近1周"列', file=sys.stderr)
        print(f"   可用列: {list(df.columns)}", file=sys.stderr)
        sys.exit(1)

    # 清洗：去除周涨幅为空的行，转为 float
    df = df.dropna(subset=["近1周"])
    df["_weekly"] = df["近1周"].astype(float)
    return df


def fetch_fund_type_map() -> dict:
    """通过 AKShare 获取基金代码 -> 基金类型 的映射（向量化）。"""
    print("📡 正在从 AKShare 拉取基金类型数据...")
    try:
        df = ak.fund_name_em()
    except Exception as e:
        print(f"❌ 获取基金类型数据失败: {e}", file=sys.stderr)
        print("   请检查网络连接或确认 AKShare 是否已正确安装", file=sys.stderr)
        sys.exit(1)
    # 向量化构建映射（比 iterrows 快 50-100 倍）
    df = df.dropna(subset=["基金代码"])
    type_map = dict(zip(df["基金代码"].astype(str), df["基金类型"].astype(str)))
    print(f"   获取到 {len(type_map)} 只基金的类型信息")
    return type_map


def get_week_range() -> str:
    """计算上周一～上周日的日期范围字符串。"""
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return f"{last_monday} ~ {last_sunday}"


def classify_funds(df: pd.DataFrame, themes: list, type_map: dict) -> dict:
    """按主题关键词将基金归类（向量化匹配）。

    对每个主题，用正则表达式一次性匹配所有基金名称，
    然后按周涨幅降序排列。全量数据 + 向量化操作，
    既不会漏掉冷门板块，也不会慢。
    """
    classified = {}

    for theme in themes:
        theme_name = theme["name"]
        # 构建正则：关键词1|关键词2|...，匹配基金名称
        pattern = "|".join(theme["keywords"])
        mask = df["基金简称"].str.contains(pattern, na=False)
        matched = df[mask]

        # 取该主题下涨幅最高的 top_n 只基金（之后在 build_result 中截断）
        matched = matched.sort_values("_weekly", ascending=False)

        funds = []
        for _, row in matched.iterrows():
            fund_code = str(row["基金代码"])
            funds.append({
                "code": fund_code,
                "name": str(row["基金简称"]),
                "weeklyReturn": float(row["_weekly"]),
                "type": type_map.get(fund_code, ""),
            })

        classified[theme_name] = funds
        print(f"   {theme_name}: 匹配到 {len(funds)} 只基金")

    return classified


def build_result(classified: dict, top_n: int, week_range: str) -> dict:
    """构建输出 JSON 结构：每主题取涨幅 Top N，排序后返回。"""
    themes_result = []
    for theme_name, funds in classified.items():
        # 去重 + 取前 N
        seen = set()
        unique = []
        for f in funds:
            if f["code"] not in seen:
                seen.add(f["code"])
                unique.append(f)
        themes_result.append({
            "name": theme_name,
            "funds": unique[:top_n],
        })

    return {
        "week": week_range,
        "updatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "themes": themes_result,
    }


def save_data(result: dict):
    """将结果写入 data/weekly/<week_start>.json 和 data/latest.json。"""
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
            print(f"   {prefix} {fund['name']:<20s} {sign}{fund['weeklyReturn']:.2f}%")
    print(f"\n{'='*50}")


def cmd_update():
    """主命令：更新周涨幅数据。"""
    config = load_config()
    week_range = get_week_range()
    print(f"📅 计算周期: {week_range}")

    df = fetch_fund_data()
    type_map = fetch_fund_type_map()
    print("🔍 正在按主题关键词匹配基金...")
    classified = classify_funds(df, config["themes"], type_map)
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

    command = sys.argv[1]
    if command == "update":
        cmd_update()
    else:
        print(f"未知命令: {command}")
        print("用法: python cli.py update")
        sys.exit(1)


if __name__ == "__main__":
    main()
