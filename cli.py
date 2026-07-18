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
    """通过 AKShare 获取全市场开放式基金排行数据（含近1周涨幅）。"""
    print("📡 正在从 AKShare 拉取全市场基金数据...")
    try:
        df = ak.fund_open_fund_rank_em(symbol="全部")
    except Exception as e:
        print(f"❌ 获取基金排行数据失败: {e}", file=sys.stderr)
        print("   请检查网络连接或确认 AKShare 是否已正确安装", file=sys.stderr)
        sys.exit(1)
    print(f"   获取到 {len(df)} 只基金")
    return df


def fetch_fund_type_map() -> dict:
    """通过 AKShare 获取所有基金的代码->类型映射。

    fund_name_em() 返回全市场基金名称和类型列表，
    我们从中提取 {"基金代码": "基金类型"} 的字典。
    """
    print("📡 正在从 AKShare 拉取基金类型数据...")
    try:
        df = ak.fund_name_em()
    except Exception as e:
        print(f"❌ 获取基金类型数据失败: {e}", file=sys.stderr)
        print("   请检查网络连接或确认 AKShare 是否已正确安装", file=sys.stderr)
        sys.exit(1)
    type_map = {}
    for _, row in df.iterrows():
        code = str(row.get("基金代码", ""))
        ftype = str(row.get("基金类型", ""))
        if code:
            type_map[code] = ftype
    print(f"   获取到 {len(type_map)} 只基金的类型信息")
    return type_map


def get_week_range() -> str:
    """计算上周一～上周日的日期范围字符串。"""
    today = datetime.now().date()
    # 找到上周一
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return f"{last_monday} ~ {last_sunday}"


def classify_funds(df: pd.DataFrame, themes: list, type_map: dict) -> dict:
    """按主题关键词将基金归类。

    Args:
        df: 包含 基金代码, 基金简称, 近1周 等列的 DataFrame
        themes: 主题配置列表
        type_map: 基金代码 -> 基金类型 的映射字典

    Returns:
        {theme_name: [fund_dict, ...]}
    """
    # 清洗：验证必要列存在，去除 近1周 为空的行，并将周涨幅转为 float
    if "近1周" not in df.columns:
        print('❌ 数据中缺少"近1周"列，无法计算周涨幅', file=sys.stderr)
        print(f"   可用列: {list(df.columns)}", file=sys.stderr)
        sys.exit(1)
    df = df.dropna(subset=["近1周"]).copy()
    df["周涨幅"] = df["近1周"].astype(float)

    classified = {t["name"]: [] for t in themes}

    for _, row in df.iterrows():
        fund_name = str(row.get("基金简称", ""))
        fund_code = str(row.get("基金代码", ""))
        fund_type = type_map.get(fund_code, "")
        weekly_return = row["周涨幅"]

        for theme in themes:
            for kw in theme["keywords"]:
                if kw in fund_name:
                    classified[theme["name"]].append({
                        "code": fund_code,
                        "name": fund_name,
                        "weeklyReturn": weekly_return,
                        "type": fund_type,
                    })
                    break  # 同一主题只匹配一次

    return classified


def build_result(classified: dict, top_n: int, week_range: str) -> dict:
    """构建输出 JSON 结构：每主题取涨幅 Top N，排序后返回。"""
    themes_result = []
    for theme_name, funds in classified.items():
        # 去重（同一基金可能在多个主题中，但当前主题内不应重复）
        seen = set()
        unique = []
        for f in funds:
            if f["code"] not in seen:
                seen.add(f["code"])
                unique.append(f)

        # 按周涨幅降序排列，取前 N
        unique.sort(key=lambda x: x["weeklyReturn"], reverse=True)
        top_funds = unique[:top_n]

        themes_result.append({
            "name": theme_name,
            "funds": top_funds,
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
