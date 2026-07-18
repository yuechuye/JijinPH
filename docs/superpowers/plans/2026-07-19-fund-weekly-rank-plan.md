# 基金周涨幅榜 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个静态网站 + Python CLI，每周从 AKShare 抓取基金涨幅数据，按主题分类后展示在 GitHub Pages 上。

**Architecture:** Python CLI 通过 AKShare 拉取全市场基金周涨幅 → 按关键词匹配主题 → 输出 JSON → 自动 git push → 纯静态 HTML/CSS/JS 网站 fetch JSON 并渲染。

**Tech Stack:** Python 3, AKShare, PyYAML, HTML5, CSS3, Vanilla JS, GitHub Pages

---

### Task 1: 项目初始化与配置

**Files:**
- Create: `config/themes.yaml`
- Create: `requirements.txt`
- Create: `.gitignore`

- [ ] **Step 1: 创建 themes.yaml 配置文件**

```yaml
# 基金主题配置
# topN: 每个主题展示的基金数量
# themes: 主题列表，keywords 用于匹配基金名称
topN: 5
themes:
  - name: 新能源
    keywords: [光伏, 新能源, 锂电, 储能, 电池, 电动汽车, 充电桩, 碳中和]
  - name: 半导体
    keywords: [半导体, 芯片, 集成电路]
  - name: 消费
    keywords: [消费, 白酒, 食品饮料, 家电, 新零售]
  - name: 医疗
    keywords: [医疗, 医药, 生物, 健康, 创新药, 中药]
  - name: 科技
    keywords: [科技, 人工智能, AI, 数字经济, 信创, 云计算, 大数据, 互联网]
  - name: 军工
    keywords: [军工, 国防, 航天, 航空, 武器装备]
  - name: 金融地产
    keywords: [金融, 银行, 券商, 保险, 地产, 证券]
  - name: 红利价值
    keywords: [红利, 高股息, 价值, 低波]
```

- [ ] **Step 2: 创建 requirements.txt**

```
akshare>=1.14.0
pyyaml>=6.0
pandas>=2.0.0
```

- [ ] **Step 3: 创建 .gitignore**

```gitignore
__pycache__/
*.pyc
.venv/
venv/
.DS_Store
*.egg-info/
```

- [ ] **Step 4: 初始化 git 仓库**

```bash
cd /Users/yuechu/MY/JijinPH
git init
git add -A
git commit -m "chore: init project with config and requirements"
```

---

### Task 2: CLI 工具核心逻辑

**Files:**
- Create: `cli.py`

- [ ] **Step 1: 写入完整的 cli.py**

```python
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
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def fetch_fund_data() -> pd.DataFrame:
    """通过 AKShare 获取全市场开放式基金排行数据（含近1周涨幅）。"""
    print("📡 正在从 AKShare 拉取全市场基金数据...")
    df = ak.fund_open_fund_rank_em(symbol="全部")
    print(f"   获取到 {len(df)} 只基金")
    return df


def get_week_range() -> str:
    """计算上周一～上周日的日期范围字符串。"""
    today = datetime.now().date()
    # 找到上周一
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return f"{last_monday} ~ {last_sunday}"


def classify_funds(df: pd.DataFrame, themes: list) -> dict:
    """按主题关键词将基金归类。

    Args:
        df: 包含 基金代码, 基金简称, 近1周 等列的 DataFrame
        themes: 主题配置列表

    Returns:
        {theme_name: [fund_dict, ...]}
    """
    # 清洗：去除 近1周 为空的行，并将周涨幅转为 float
    df = df.dropna(subset=["近1周"])
    df["周涨幅"] = df["近1周"].astype(float)

    classified = {t["name"]: [] for t in themes}

    for _, row in df.iterrows():
        fund_name = str(row.get("基金简称", ""))
        fund_code = str(row.get("基金代码", ""))
        fund_type = str(row.get("基金类型", ""))
        weekly_return = float(row["周涨幅"])

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
        week_file = sorted(WEEKLY_DIR.glob("*.json"))[-1]
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
    print("🔍 正在按主题关键词匹配基金...")
    classified = classify_funds(df, config["themes"])
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
```

- [ ] **Step 2: 安装 Python 依赖并验证 CLI 可运行**

```bash
cd /Users/yuechu/MY/JijinPH
pip install -r requirements.txt
python cli.py  # 应输出用法提示
```

- [ ] **Step 3: 试运行 CLI 更新命令（仅拉数据不 push）**

```bash
cd /Users/yuechu/MY/JijinPH
python cli.py update
# 等待数据拉取，期间输入 n 跳过推送
# 验证 data/latest.json 和 data/weekly/*.json 已生成
```

- [ ] **Step 4: 提交 CLI 代码**

```bash
git add cli.py requirements.txt
git commit -m "feat: add CLI tool for weekly fund rank update"
```

---

### Task 3: 网站前端

**Files:**
- Create: `index.html`
- Create: `style.css`
- Create: `script.js`

- [ ] **Step 1: 创建 index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>基金周涨幅榜</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="container">
  <header class="header">
    <h1>📈 基金周涨幅榜</h1>
    <p id="week-range" class="week-range">加载中...</p>
  </header>

  <nav id="tab-bar" class="tab-bar"></nav>

  <main id="fund-list" class="fund-list">
    <div class="loading">加载中...</div>
  </main>

  <footer class="footer">
    <p>数据来源：天天基金 · 更新时间：<span id="update-time">--</span></p>
  </footer>
</div>
<script src="script.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 style.css**

```css
/* ===== Reset & Base ===== */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #f5f5f5;
  --card-bg: #ffffff;
  --text: #333333;
  --text-secondary: #888888;
  --up: #e53e3e;
  --down: #38a169;
  --accent: #3182ce;
  --accent-light: #ebf8ff;
  --gold: #d69e2e;
  --silver: #a0aec0;
  --bronze: #c05621;
  --radius: 12px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}

/* ===== Container ===== */
.container {
  max-width: 720px;
  margin: 0 auto;
  padding: 20px 16px;
}

/* ===== Header ===== */
.header {
  text-align: center;
  padding: 32px 0 20px;
}
.header h1 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
}
.week-range {
  margin-top: 6px;
  font-size: 14px;
  color: var(--text-secondary);
}

/* ===== Tab Bar ===== */
.tab-bar {
  display: flex;
  gap: 8px;
  padding: 4px 0 16px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.tab-bar::-webkit-scrollbar { display: none; }

.tab-btn {
  flex-shrink: 0;
  padding: 8px 18px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: var(--card-bg);
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  user-select: none;
}
.tab-btn:hover { border-color: var(--accent); color: var(--accent); }
.tab-btn.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

/* ===== Fund List ===== */
.fund-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 200px;
}

.loading {
  text-align: center;
  color: var(--text-secondary);
  padding: 60px 20px;
  font-size: 16px;
}

/* ===== Fund Card ===== */
.fund-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--card-bg);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  transition: transform 0.15s;
}
.fund-card:hover { transform: translateY(-1px); }

.fund-rank {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
  border-radius: 8px;
  background: #edf2f7;
  color: var(--text-secondary);
}
.fund-rank.gold   { background: #fefcbf; color: #975a16; }
.fund-rank.silver { background: #e2e8f0; color: #4a5568; }
.fund-rank.bronze { background: #fed7d7; color: #7b341e; }

.fund-info {
  flex: 1;
  min-width: 0;
}
.fund-name {
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fund-type {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.fund-return {
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
  text-align: right;
}
.fund-return.up   { color: var(--up); }
.fund-return.down { color: var(--down); }

/* ===== Empty State ===== */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-secondary);
  font-size: 14px;
}

/* ===== Footer ===== */
.footer {
  text-align: center;
  padding: 24px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

/* ===== Responsive ===== */
@media (max-width: 480px) {
  .container { padding: 12px 10px; }
  .header h1 { font-size: 22px; }
  .fund-card { padding: 12px 14px; gap: 8px; }
  .fund-return { font-size: 16px; }
}
```

- [ ] **Step 3: 创建 script.js**

```javascript
(async function () {
  const tabBar = document.getElementById("tab-bar");
  const fundList = document.getElementById("fund-list");
  const weekRange = document.getElementById("week-range");
  const updateTime = document.getElementById("update-time");

  let data = null;
  let activeThemeIndex = 0;

  // ===== Fetch Data =====
  async function loadData() {
    try {
      const resp = await fetch("data/latest.json");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
      return true;
    } catch (err) {
      console.error("加载数据失败:", err);
      fundList.innerHTML =
        '<div class="empty-state">⚠️ 暂无数据，请先运行 CLI 更新</div>';
      weekRange.textContent = "--";
      return false;
    }
  }

  // ===== Render Header =====
  function renderHeader() {
    weekRange.textContent = data.week;
    updateTime.textContent = data.updatedAt;
  }

  // ===== Render Tab Bar =====
  function renderTabs() {
    tabBar.innerHTML = "";
    data.themes.forEach((theme, index) => {
      const btn = document.createElement("button");
      btn.className = "tab-btn";
      if (index === activeThemeIndex) btn.classList.add("active");
      btn.textContent = theme.name;
      btn.addEventListener("click", () => {
        activeThemeIndex = index;
        renderTabs();
        renderFunds();
      });
      tabBar.appendChild(btn);
    });
  }

  // ===== Render Fund Cards =====
  function renderFunds() {
    const theme = data.themes[activeThemeIndex];
    if (!theme || !theme.funds.length) {
      fundList.innerHTML =
        '<div class="empty-state">该板块暂无匹配基金</div>';
      return;
    }

    const medals = ["gold", "silver", "bronze"];
    const medalEmoji = ["🥇", "🥈", "🥉"];

    fundList.innerHTML = theme.funds
      .map((fund, i) => {
        const medalClass = i < 3 ? medals[i] : "";
        const rankDisplay =
          i < 3
            ? medalEmoji[i]
            : `<span class="fund-rank">${i + 1}</span>`;
        const returnClass = fund.weeklyReturn >= 0 ? "up" : "down";
        const sign = fund.weeklyReturn >= 0 ? "+" : "";

        let rankHtml;
        if (i < 3) {
          rankHtml = `<div class="fund-rank ${medalClass}">${rankDisplay}</div>`;
        } else {
          rankHtml = `<div class="fund-rank">${i + 1}</div>`;
        }

        return `
          <div class="fund-card">
            ${rankHtml}
            <div class="fund-info">
              <div class="fund-name">${escapeHtml(fund.name)}</div>
              <div class="fund-type">${escapeHtml(fund.type)}</div>
            </div>
            <div class="fund-return ${returnClass}">${sign}${fund.weeklyReturn.toFixed(2)}%</div>
          </div>
        `;
      })
      .join("");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ===== Run =====
  const ok = await loadData();
  if (!ok) return;

  renderHeader();
  renderTabs();
  renderFunds();
})();
```

- [ ] **Step 4: 提交网站代码**

```bash
git add index.html style.css script.js
git commit -m "feat: add static website for fund weekly rank display"
```

---

### Task 4: 集成验证与最终设置

- [ ] **Step 1: 确认 .gitignore 排除 data/ 目录外的无关文件，但 data/ 本身需要被跟踪**

检查 `.gitignore` 中没有 `data/`，确保数据 JSON 文件会被 git 跟踪并推送到 GitHub。

- [ ] **Step 2: 验证完整流程**

```bash
cd /Users/yuechu/MY/JijinPH
# 运行 CLI
python cli.py update
# 输入 n 跳过推送（先本地检查）
# 打开 index.html 查看效果
open index.html   # 或在浏览器中直接打开
```

- [ ] **Step 3: 在 GitHub 上创建仓库并推送**

```bash
# 确认 data/ 目录已正确生成
ls data/latest.json
ls data/weekly/

# 推送到 GitHub（用户需先在 GitHub 创建仓库）
# git remote add origin <your-repo-url>
# git push -u origin main
```

- [ ] **Step 4: 启用 GitHub Pages**

在 GitHub 仓库的 Settings → Pages 中，将 Source 设置为 `main` 分支根目录（或 `docs/` 如果选择该选项），保存后等待部署完成。

- [ ] **Step 5: 提交最终确认**

```bash
git add -A
git commit -m "chore: finalize project setup"
git push origin main
```
