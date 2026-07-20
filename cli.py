#!/usr/bin/env python3
"""基金周涨幅榜 CLI — 每周获取精选场内 ETF 的周涨幅。

数据源: api.fund.eastmoney.com 净值接口（官方单位净值）
计算: (周五净值 / 周一净值 - 1) × 100，纯自己算
"""

import json
import math
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


def get_week_range(start_date: str, end_date: str) -> str:
    """根据计算用的起止日生成展示用的周范围字符串。"""
    return f"{start_date} ~ {end_date}"


def get_momentum_dates() -> dict[str, str]:
    """返回动量计算所需的全部日期。

    阶段一（排名）使用: friday_before（上周五）和 thursday（本周四）
    阶段二（动量）额外使用: T-1, T-2, T-4, T-12（均为周四）

    返回 dict，所有值为 "YYYY-MM-DD" 格式字符串。
    """
    today = datetime.now().date()

    # 找最近的周四（阶段一终点 / 阶段二 T0）
    days_since_thursday = (today.weekday() - 3) % 7
    thursday = today - timedelta(days=days_since_thursday)

    # 上周五（阶段一起点）
    # 周四往前数 6 天 = 上周五
    friday_before = thursday - timedelta(days=6)

    # 动量时间点：均为周四
    t_minus_1 = thursday - timedelta(weeks=1)   # 1周前
    t_minus_2 = thursday - timedelta(weeks=2)   # 2周前
    t_minus_4 = thursday - timedelta(weeks=4)   # 4周前
    t_minus_12 = thursday - timedelta(weeks=12) # 12周前

    return {
        "friday_before": friday_before.strftime("%Y-%m-%d"),
        "thursday": thursday.strftime("%Y-%m-%d"),
        "t_minus_1": t_minus_1.strftime("%Y-%m-%d"),
        "t_minus_2": t_minus_2.strftime("%Y-%m-%d"),
        "t_minus_4": t_minus_4.strftime("%Y-%m-%d"),
        "t_minus_12": t_minus_12.strftime("%Y-%m-%d"),
    }


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


def fetch_one_nav(code: str, date_str: str) -> float | None:
    """获取某只ETF在某日的单位净值。

    如果当天非交易日，取最近一个不晚于该日的交易日净值。
    date_str 格式: YYYY-MM-DD
    """
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        # API 使用 YYYYMMDD 格式
        start_date = (target_date - timedelta(days=10)).strftime("%Y%m%d")
        end_date = target_date.strftime("%Y%m%d")

        df = ak.fund_etf_fund_info_em(
            fund=code,
            start_date=start_date,
            end_date=end_date,
        )
        if len(df) == 0:
            return None

        # 取最接近 target_date 且不晚于它的净值记录
        target_ts = pd.Timestamp(target_date.strftime("%Y-%m-%d"))
        df["净值日期"] = pd.to_datetime(df["净值日期"])
        valid = df[df["净值日期"] <= target_ts]
        if len(valid) == 0:
            return None

        nav = float(valid.iloc[-1]["单位净值"])
        return nav
    except Exception:
        return None


def fetch_one_etf_momentum(code: str, dates: dict) -> dict | None:
    """获取一只ETF的周涨幅和动量得分。

    Args:
        code: ETF代码
        dates: get_momentum_dates() 返回的日期 dict (所有值均为 YYYY-MM-DD 格式)

    Returns:
        None 或 {"weeklyReturn": float, "momentumScore": float, "returns": dict}
    """
    try:
        # 取各时间点净值
        t0 = fetch_one_nav(code, dates["thursday"])
        time.sleep(0.1)
        t_m1 = fetch_one_nav(code, dates["t_minus_1"])
        time.sleep(0.1)
        t_m2 = fetch_one_nav(code, dates["t_minus_2"])
        time.sleep(0.1)
        t_m4 = fetch_one_nav(code, dates["t_minus_4"])
        time.sleep(0.1)
        t_m12 = fetch_one_nav(code, dates["t_minus_12"])
        time.sleep(0.1)
        fri_nav = fetch_one_nav(code, dates["friday_before"])

        # 阶段一：周涨幅 = (周四净值 / 上周五净值 - 1) × 100
        if t0 is None or fri_nav is None or fri_nav == 0:
            weekly_return = None
        else:
            weekly_return = round((t0 / fri_nav - 1) * 100, 2)
            # NaN guard
            if math.isnan(weekly_return) or math.isinf(weekly_return):
                weekly_return = None

        # 阶段二：动量得分
        momentum = _calc_momentum_score(t0, t_m1, t_m2, t_m4, t_m12)

        if weekly_return is None and momentum is None:
            return None

        return {
            "weeklyReturn": weekly_return,
            "momentumScore": momentum["score"] if momentum else None,
            "returns": momentum["returns"] if momentum else None,
        }
    except Exception:
        return None


def _calc_momentum_score(t0: float | None, t_m1: float | None,
                         t_m2: float | None, t_m4: float | None,
                         t_m12: float | None) -> dict | None:
    """计算动量得分。

    加权公式: 1周×40% + 2周×30% + 4周×20% + 12周×10%
    缺失周期按比例重新分配权重。
    可用周期 < 2 则返回 None。

    Returns:
        None 或 {"score": float, "returns": {"1w": float|None, ...}}
    """
    if t0 is None or t0 == 0:
        return None

    periods = [
        ("1w", t_m1, 0.4),
        ("2w", t_m2, 0.3),
        ("4w", t_m4, 0.2),
        ("12w", t_m12, 0.1),
    ]

    returns: dict[str, float | None] = {}
    available_weight = 0.0
    weighted_sum = 0.0

    for label, nav, weight in periods:
        if nav is not None and nav > 0:
            r = (t0 / nav - 1) * 100
            # NaN guard
            if not math.isnan(r) and not math.isinf(r):
                returns[label] = round(r, 2)
                weighted_sum += r * weight
                available_weight += weight
            else:
                returns[label] = None
        else:
            returns[label] = None

    # 可用周期 < 2，不参与动量评分
    available_count = sum(1 for v in returns.values() if v is not None)
    if available_count < 2 or available_weight == 0:
        return None

    # 按比例重新分配权重
    score = round(weighted_sum / available_weight, 2)

    return {"score": score, "returns": returns}


def fetch_all_weekly(codes: list, monday: str, friday: str) -> dict:
    """获取所有 ETF 的周涨幅。"""
    total = len(codes)
    results = {}
    failed = 0

    print(f"📡 正在获取 {total} 只 ETF 的净值周涨幅...")

    for i, code in enumerate(codes):
        ret = fetch_one_etf_weekly(code, monday, friday)
        if ret is not None:
            results[code] = ret
        else:
            failed += 1

        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"   进度: {i+1}/{total} (成功 {len(results)}, 失败 {failed})")

        time.sleep(0.2)

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
