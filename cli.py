#!/usr/bin/env python3
"""基金周涨幅榜 CLI — 从 AKShare 拉取数据，生成 JSON 并推送。

数据获取策略（按优先级降级）：
  1. fund_etf_hist_em(symbol, period="weekly") — ETF 自身周涨幅（最准确）
  2. fund_open_fund_rank_em 的 近1周 → 匹配 ETF 联接基金（降级方案）
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# 并发请求数
MAX_WORKERS = 6


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


def get_week_dates():
    """返回上周一和上周五的日期。"""
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday, last_friday


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
    """获取真正的场内 ETF 列表（含代码和名称）。"""
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


def fetch_one_etf_weekly(code: str, monday: datetime, friday: datetime):
    """通过 fund_etf_hist_em 获取单只 ETF 上周的周涨幅。

    Returns:
        {"code": str, "weeklyReturn": float} 或 None（失败时）
    """
    try:
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="weekly",
            start_date=monday.strftime("%Y%m%d"),
            end_date=friday.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if len(df) == 0:
            return None
        row = df.iloc[-1]
        weekly = float(row["涨跌幅"])
        return {"code": code, "weeklyReturn": weekly}
    except Exception:
        return None


def fetch_etf_weekly_bulk(codes: list[str], monday: datetime, friday: datetime) -> dict:
    """并发获取多只 ETF 的周涨幅。

    Returns:
        {code: weeklyReturn}
    """
    results = {}
    failed = []
    total = len(codes)

    print(f"📡 正在并发获取 {total} 只 ETF 的周涨幅（{MAX_WORKERS} 线程）...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_one_etf_weekly, code, monday, friday): code
            for code in codes
        }
        done_count = 0
        for future in as_completed(futures):
            code = futures[future]
            done_count += 1
            try:
                r = future.result()
                if r:
                    results[r["code"]] = r["weeklyReturn"]
                else:
                    failed.append(code)
            except Exception:
                failed.append(code)
            if done_count % 50 == 0 or done_count == total:
                print(f"   进度: {done_count}/{total} (成功 {len(results)}, 失败 {len(failed)})")

    if failed:
        print(f"   ⚠️  {len(failed)} 只 ETF 获取失败，将用联接基金数据降级")
    return results


def fetch_fallback_weekly(etf_df: pd.DataFrame) -> pd.DataFrame:
    """降级方案：通过 fund_open_fund_rank_em + ETF 联接基金匹配获取周涨幅。"""
    print("📡 降级：从基金排行 + ETF 联接匹配获取周涨幅...")
    try:
        rank = ak.fund_open_fund_rank_em(symbol="全部")
    except Exception as e:
        print(f"❌ 获取基金排行数据失败: {e}", file=sys.stderr)
        sys.exit(1)

    if "近1周" not in rank.columns:
        print('❌ 排行数据中缺少"近1周"列', file=sys.stderr)
        sys.exit(1)

    rank = rank.dropna(subset=["近1周"])
    rank["_weekly"] = rank["近1周"].astype(float)
    # 只保留 ETF 相关基金
    rank = rank[rank["基金简称"].str.contains("ETF", na=False)]

    rows = []
    matched_codes = set()

    for _, etf in etf_df.iterrows():
        name = str(etf["name"])
        code = str(etf["code"])
        keywords = name.replace("ETF", " ").split()
        if not keywords:
            continue
        mask = rank["基金简称"].str.contains(keywords[0], na=False)
        for kw in keywords[1:]:
            mask &= rank["基金简称"].str.contains(kw, na=False)
        matches = rank[mask]
        if len(matches) == 0:
            continue

        fund = matches.iloc[0]
        fund_code = str(fund["基金代码"])
        if fund_code not in matched_codes:
            matched_codes.add(fund_code)
            rows.append({
                "code": code,
                "name": name,
                "fund_code": fund_code,
                "fund_name": str(fund["基金简称"]),
                "_weekly": float(fund["_weekly"]),
            })

    print(f"   联接基金匹配: {len(rows)} 只")
    return pd.DataFrame(rows)


def fetch_fund_type_map() -> dict:
    """通过 AKShare 获取基金代码 -> 基金类型 的映射。"""
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


def classify_etfs(etf_df: pd.DataFrame, themes: list, weekly_map: dict,
                  type_map: dict) -> dict:
    """按主题关键词将 ETF 归类。

    weekly_map: {etf_code: weeklyReturn} — 优先使用 ETF 自身周涨幅
    """
    classified = {}

    for theme in themes:
        theme_name = theme["name"]
        pattern = "|".join(theme["keywords"])
        mask = etf_df["name"].str.contains(pattern, na=False)
        matched = etf_df[mask].copy()

        # 填入周涨幅：优先 ETF 自身数据，其次联接基金数据
        def get_weekly(row):
            code = str(row["code"])
            if code in weekly_map:
                return weekly_map[code]
            return float(row.get("_weekly", 0))

        matched["_return"] = matched.apply(get_weekly, axis=1)
        matched = matched.sort_values("_return", ascending=False)

        funds = []
        seen = set()
        for _, row in matched.iterrows():
            code = str(row["code"])
            if code in seen:
                continue
            seen.add(code)
            funds.append({
                "code": code,
                "name": str(row["name"]),
                "weeklyReturn": float(row["_return"]),
                "type": type_map.get(str(row.get("fund_code", "")), ""),
                "source": "etf" if code in weekly_map else "fallback",
            })

        classified[theme_name] = funds
        etf_count = sum(1 for f in funds if f["source"] == "etf")
        print(f"   {theme_name}: {len(funds)} 只 (ETF直连:{etf_count})")

    return classified


def build_result(classified: dict, top_n: int, week_range: str) -> dict:
    """构建输出 JSON 结构：每主题取涨幅 Top N。"""
    themes_result = []
    for theme_name, funds in classified.items():
        seen = set()
        unique = []
        for f in funds:
            if f["code"] not in seen:
                seen.add(f["code"])
                unique.append(f)
        themes_result.append({
            "name": theme_name,
            "funds": [{k: v for k, v in f.items() if k != "source"} for f in unique[:top_n]],
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

    save_manifest()


def save_manifest():
    """扫描 data/weekly/ 目录，生成 manifest.json 列出所有可用周。"""
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

    manifest = {"weeks": weeks}
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
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
            print(f"   {prefix} {fund['name']:<20s} {sign}{fund['weeklyReturn']:.2f}%")
    print(f"\n{'='*50}")


# ============================================================
# 主命令
# ============================================================


def cmd_update():
    """主命令：更新周涨幅数据。"""
    config = load_config()
    week_range = get_week_range()
    monday, friday = get_week_dates()
    print(f"📅 计算周期: {week_range}")
    print(f"   交易日: {monday} ~ {friday}")

    # 1. 拉取场内 ETF 列表
    etf_df = fetch_etf_spot()

    # 2. 按主题关键词预筛选，收集需要查询的 ETF 代码
    print("🔍 按关键词预筛选 ETF...")
    all_matched_codes = set()
    for theme in config["themes"]:
        pattern = "|".join(theme["keywords"])
        mask = etf_df["name"].str.contains(pattern, na=False)
        for code in etf_df[mask]["code"]:
            all_matched_codes.add(str(code))
    print(f"   共 {len(all_matched_codes)} 只 ETF 匹配主题关键词")

    # 3. 并发获取 ETF 自身周涨幅（主方案）
    weekly_map = fetch_etf_weekly_bulk(list(all_matched_codes), monday, friday)

    # 4. 对获取失败的 ETF，用联接基金降级
    if len(weekly_map) < len(all_matched_codes):
        fallback_df = fetch_fallback_weekly(
            etf_df[~etf_df["code"].astype(str).isin(weekly_map.keys())]
        )
        # 合并：ETF 直连数据优先
        for _, row in fallback_df.iterrows():
            code = str(row["code"])
            if code not in weekly_map:
                weekly_map[code] = float(row["_weekly"])
        # 也把联接基金的额外信息合并到 etf_df
        etf_df = etf_df.merge(
            fallback_df[["code", "fund_code", "fund_name", "_weekly"]],
            on="code", how="left",
        )
    else:
        etf_df["fund_code"] = ""
        etf_df["fund_name"] = ""
        etf_df["_weekly"] = 0.0

    # 5. 拉取基金类型
    type_map = fetch_fund_type_map()

    # 6. 按主题分类
    print("🔍 正在按主题关键词归类...")
    classified = classify_etfs(etf_df, config["themes"], weekly_map, type_map)

    # 7. 生成结果
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
