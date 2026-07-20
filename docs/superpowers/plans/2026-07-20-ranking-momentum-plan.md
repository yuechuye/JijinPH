# 周涨幅排名优化 + 动量评分系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将计算窗口从「周一→周五」改为「周五→周四」，并新增多周期动量评分系统（1周/2周/4周/12周加权）

**Architecture:** 纯 Python CLI (`cli.py`) 负责数据获取与计算，JSON 文件存储结果，静态 HTML/JS/CSS 前端展示。改动集中在 `cli.py`（日期逻辑 + 动量计算 + 输出格式）和前端三件套（新增动量总榜Tab）

**Tech Stack:** Python 3, akshare, pandas, yaml, 原生 JS/CSS/HTML

---

## 文件结构

```
cli.py          ← 核心改动: get_momentum_dates(), fetch_one_etf_momentum(), 动量排名生成
script.js       ← 新增: 动量总榜Tab渲染, momentumRanking数据消费
index.html      ← 新增: "动量榜"Tab按钮(硬编码在tab-bar,或由JS动态生成)
style.css       ← 新增: 动量得分样式
```

---

### Task 1: 改写日期函数 `get_trading_dates()` → `get_momentum_dates()`

**Files:**
- Modify: `cli.py:56-62` (替换 `get_trading_dates`)
- Modify: `cli.py:45-53` (替换 `get_week_range`)

- [ ] **Step 1: 替换 `get_week_range()` 和 `get_trading_dates()` 为新的日期函数**

将两个函数合并重写。找到 `cli.py` 中的两个函数，替换为：

```python
def get_week_range(start_date, end_date):
    """根据计算用的起止日生成展示用的周范围字符串。"""
    return f"{start_date} ~ {end_date}"


def get_momentum_dates():
    """返回动量计算所需的全部日期。

    阶段一（排名）使用: friday_before（上周五）和 thursday（本周四）
    阶段二（动量）额外使用: T-1, T-2, T-4, T-12（均为周四）

    返回 dict，所有值为 "YYYYMMDD" 格式字符串。
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
        "friday_before": friday_before.strftime("%Y%m%d"),
        "thursday": thursday.strftime("%Y%m%d"),
        "t_minus_1": t_minus_1.strftime("%Y%m%d"),
        "t_minus_2": t_minus_2.strftime("%Y%m%d"),
        "t_minus_4": t_minus_4.strftime("%Y%m%d"),
        "t_minus_12": t_minus_12.strftime("%Y%m%d"),
    }
```

- [ ] **Step 2: 验证日期计算逻辑**

```bash
python3 -c "
from datetime import datetime, timedelta
today = datetime.now().date()
# 模拟 get_momentum_dates 逻辑
days_since_thursday = (today.weekday() - 3) % 7
thursday = today - timedelta(days=days_since_thursday)
friday_before = thursday - timedelta(days=6)
print(f'今天: {today} (周{today.weekday()+1})')
print(f'周四: {thursday} (周{thursday.weekday()+1})')
print(f'周五: {friday_before} (周{friday_before.weekday()+1})')
"
```

预期：周四显示为周4，周五显示为周5。

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "refactor: replace get_trading_dates with get_momentum_dates (Fri→Thu window)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 新增 `fetch_one_nav()` 辅助函数 + 重写 `fetch_one_etf_weekly()` 为 `fetch_one_etf_momentum()`

**Files:**
- Modify: `cli.py:78-113` (替换 `fetch_one_etf_weekly`)

- [ ] **Step 1: 新增 `fetch_one_nav()` 辅助函数**

在 `fetch_one_etf_weekly` 上方插入：

```python
def fetch_one_nav(code: str, date_str: str):
    """获取某只ETF在某日的单位净值。如果当天非交易日，取最近一个交易日的净值。

    返回 float 或 None。
    """
    try:
        # 往前多取几天，以防 target_date 是非交易日
        target_date = datetime.strptime(date_str, "%Y%m%d")
        start_date = (target_date - timedelta(days=5)).strftime("%Y%m%d")

        df = ak.fund_etf_fund_info_em(
            fund=code,
            start_date=start_date,
            end_date=date_str,
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
```

- [ ] **Step 2: 替换 `fetch_one_etf_weekly()` 为 `fetch_one_etf_momentum()`**

删除原 `fetch_one_etf_weekly` 函数（约35行），替换为：

```python
def fetch_one_etf_momentum(code: str, dates: dict):
    """获取一只ETF的周涨幅和动量得分。

    Args:
        code: ETF代码
        dates: get_momentum_dates() 返回的日期 dict

    Returns:
        None 或 {"weeklyReturn": float, "momentumScore": float, "returns": dict}
    """
    try:
        # 取各时间点净值
        t0 = fetch_one_nav(code, dates["thursday"])
        t_m1 = fetch_one_nav(code, dates["t_minus_1"])
        t_m2 = fetch_one_nav(code, dates["t_minus_2"])
        t_m4 = fetch_one_nav(code, dates["t_minus_4"])
        t_m12 = fetch_one_nav(code, dates["t_minus_12"])
        fri_nav = fetch_one_nav(code, dates["friday_before"])

        # 阶段一：周涨幅 = (周四净值 / 上周五净值 - 1) × 100
        if t0 is None or fri_nav is None or fri_nav == 0:
            weekly_return = None
        else:
            weekly_return = round((t0 / fri_nav - 1) * 100, 2)
            # NaN guard
            if weekly_return != weekly_return or abs(weekly_return) == float("inf"):
                weekly_return = None

        # 阶段二：动量得分
        momentum = _calc_momentum_score(code, t0, t_m1, t_m2, t_m4, t_m12)

        if weekly_return is None and momentum is None:
            return None

        return {
            "weeklyReturn": weekly_return,
            "momentumScore": momentum["score"] if momentum else None,
            "returns": momentum["returns"] if momentum else None,
        }
    except Exception:
        return None


def _calc_momentum_score(code, t0, t_m1, t_m2, t_m4, t_m12):
    """计算动量得分。

    加权公式: 1周×40% + 2周×30% + 4周×20% + 12周×10%
    缺失周期按比例重新分配权重。

    Returns:
        None 或 {"score": float, "returns": {"1w": float, ...}}
    """
    if t0 is None or t0 == 0:
        return None

    periods = [
        ("1w", t_m1, 0.4),
        ("2w", t_m2, 0.3),
        ("4w", t_m4, 0.2),
        ("12w", t_m12, 0.1),
    ]

    returns = {}
    available_weight = 0.0
    weighted_sum = 0.0

    for label, nav, weight in periods:
        if nav is not None and nav > 0:
            r = (t0 / nav - 1) * 100
            # NaN guard
            if r == r and abs(r) != float("inf"):
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
```

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat: add fetch_one_etf_momentum with multi-period momentum scoring

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 更新批量获取函数 `fetch_all_weekly()` → `fetch_all_momentum()`

**Files:**
- Modify: `cli.py:116-138`

- [ ] **Step 1: 替换函数**

```python
def fetch_all_momentum(codes: list, dates: dict) -> dict:
    """获取所有 ETF 的周涨幅和动量得分。"""
    total = len(codes)
    results = {}
    failed = 0

    print(f"📡 正在获取 {total} 只 ETF 的净值数据（周涨幅 + 动量得分）...")

    for i, code in enumerate(codes):
        ret = fetch_one_etf_momentum(code, dates)
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
```

- [ ] **Step 2: Commit**

```bash
git add cli.py
git commit -m "refactor: rename fetch_all_weekly to fetch_all_momentum

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 更新 `build_result()` 以输出动量数据

**Files:**
- Modify: `cli.py:141-165`

- [ ] **Step 1: 重写 `build_result()`**

```python
def build_result(config: dict, name_map: dict, momentum_data: dict, week_range: str) -> dict:
    """构建输出 JSON，包含主题排名和动量总榜。"""
    themes_result = []
    all_funds = []  # 跨主题动量总榜

    for theme in config["themes"]:
        funds = []
        for code in theme["funds"]:
            if code in momentum_data:
                md = momentum_data[code]
                entry = {
                    "code": code,
                    "name": name_map.get(code, code),
                    "weeklyReturn": md["weeklyReturn"],
                    "momentumScore": md["momentumScore"],
                    "returns": md.get("returns"),
                    "type": "",
                }
                funds.append(entry)
                # 只有有动量得分的才进入总榜
                if md["momentumScore"] is not None:
                    all_funds.append({
                        "code": code,
                        "name": name_map.get(code, code),
                        "theme": theme["name"],
                        "momentumScore": md["momentumScore"],
                    })

        # 按周涨幅降序
        funds.sort(key=lambda x: x["weeklyReturn"] if x["weeklyReturn"] is not None else float("-inf"), reverse=True)
        themes_result.append({
            "name": theme["name"],
            "funds": funds[:config["topN"]],
        })

    # 动量总榜按 momentumScore 降序
    all_funds.sort(key=lambda x: x["momentumScore"], reverse=True)

    return {
        "week": week_range,
        "updatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "themes": themes_result,
        "momentumRanking": all_funds[:20],  # 总榜取前20
    }
```

- [ ] **Step 2: Commit**

```bash
git add cli.py
git commit -m "feat: extend build_result to output momentum ranking

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 更新 `print_summary()` 和 `cmd_update()`

**Files:**
- Modify: `cli.py:232-310`

- [ ] **Step 1: 在 `print_summary()` 末尾添加动量总榜输出**

在 `print_summary` 函数末尾（`print(f"\n{'='*50}")` 之前）插入：

```python
    # 动量总榜 Top5
    if result.get("momentumRanking"):
        print(f"\n🚀 动量总榜 Top5（跨主题）")
        print(f"   {'─'*40}")
        for i, fund in enumerate(result["momentumRanking"][:5]):
            theme_tag = f"[{fund['theme']}]"
            print(f"   {i+1}. {fund['code']} {fund['name']:<14s} {theme_tag:<12s} 动量: {fund['momentumScore']:.2f}")
```

- [ ] **Step 2: 更新 `cmd_update()` 使用新函数**

```python
def cmd_update():
    """主命令：更新周涨幅数据。"""
    config = load_config()
    dates = get_momentum_dates()
    week_range = get_week_range(dates["friday_before"], dates["thursday"])

    print(f"📅 计算周期: {week_range}")
    print(f"   交易日: {dates['friday_before']}(周五) ~ {dates['thursday']}(周四)")

    # 1. 收集所有 ETF 代码（去重）
    all_codes = list(dict.fromkeys(
        code for theme in config["themes"] for code in theme["funds"]
    ))
    print(f"📊 共 {len(config['themes'])} 个板块, {len(all_codes)} 只精选 ETF")

    # 2. 获取 ETF 名称映射
    name_map = fetch_etf_name_map()

    # 3. 获取净值数据（周涨幅 + 动量得分）
    momentum_data = fetch_all_momentum(all_codes, dates)

    # 4. 构建结果
    result = build_result(config, name_map, momentum_data, week_range)
    save_data(result)
    print_summary(result)

    # 确认推送
    answer = input("\n📤 是否 commit & push 到 GitHub? [Y/n]: ").strip().lower()
    if answer in ("", "y", "yes"):
        git_commit_and_push()
    else:
        print("⏭️  跳过推送，数据已本地保存")
```

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat: update cmd_update and print_summary for momentum system

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 前端 — 新增动量总榜Tab

**Files:**
- Modify: `index.html:22-23` (tab-bar 区域)
- Modify: `script.js` (新增动量榜渲染逻辑)
- Modify: `style.css` (动量得分样式)

- [ ] **Step 1: 更新 `index.html` — 在 tab-bar 中添加动量榜按钮**

在 `<nav id="tab-bar" ...></nav>` 内部，作为第一个子元素插入：

```html
  <nav id="tab-bar" class="tab-bar" role="tablist" aria-label="投资主题">
    <!-- 按钮由 JS 动态生成 -->
  </nav>
```

实际不改 HTML，所有Tab按钮由JS动态生成（已有逻辑）。只需确保JS能生成动量榜按钮。

- [ ] **Step 2: 更新 `script.js` — 新增动量榜渲染**

在 `renderTabs()` 函数开头（`tabBar.innerHTML = "";` 之后），第一个插入动量榜按钮：

```javascript
  function renderTabs() {
    tabBar.innerHTML = "";

    // 动量总榜按钮 (index = -2)
    if (data.momentumRanking && data.momentumRanking.length > 0) {
      const momentumBtn = document.createElement("button");
      momentumBtn.className = "tab-btn momentum-tab";
      momentumBtn.setAttribute("role", "tab");
      momentumBtn.setAttribute("aria-selected", activeThemeIndex === -2 ? "true" : "false");
      if (activeThemeIndex === -2) momentumBtn.classList.add("active");
      momentumBtn.textContent = "🚀 动量榜";
      momentumBtn.addEventListener("click", () => {
        activeThemeIndex = -2;
        renderTabs();
        renderFunds();
      });
      tabBar.appendChild(momentumBtn);
    }

    // 总榜按钮 (index = -1)
    const overallBtn = document.createElement("button");
    // ... 现有代码保持不变 ...
```

在 `renderFunds()` 函数中，于 `if (activeThemeIndex === -1)` 之前插入动量榜分支：

```javascript
  function renderFunds() {
    let funds;

    if (activeThemeIndex === -2) {
      // 动量总榜
      funds = (data.momentumRanking || []).map((f, i) => ({
        name: f.name,
        code: f.code,
        weeklyReturn: null,
        momentumScore: f.momentumScore,
        theme: f.theme,
        _momentumRank: i,
      }));
    } else if (activeThemeIndex === -1) {
      // 总榜：合并所有主题，去重，取涨幅前10
      funds = buildOverallRanking();
    } else {
      // ... 现有主题分支保持不变 ...
```

更新卡片的渲染逻辑（`fundList.innerHTML = ...` 部分），当显示动量榜时展示动量得分而非周涨幅：

```javascript
    fundList.innerHTML = funds
      .filter((fund) => {
        // 动量榜不过滤（momentumScore 保证非 null）
        if (activeThemeIndex === -2) return true;
        return fund.weeklyReturn != null && !isNaN(fund.weeklyReturn);
      })
      .map((fund, i) => {
        const medalClass = i < 3 ? medals[i] : "";
        const isMomentum = activeThemeIndex === -2;

        // 动量榜使用 momentumScore，其他使用 weeklyReturn
        const displayValue = isMomentum ? fund.momentumScore : fund.weeklyReturn;
        const returnClass = displayValue != null && displayValue >= 0 ? "up" : "down";
        const sign = displayValue != null && displayValue >= 0 ? "+" : "";
        const valueStr = displayValue != null ? `${sign}${displayValue.toFixed(2)}` : "--";

        let rankHtml;
        if (i < 3) {
          rankHtml = `<div class="fund-rank ${medalClass}">${medalEmoji[i]}</div>`;
        } else {
          rankHtml = `<div class="fund-rank">${i + 1}</div>`;
        }

        // 动量榜显示所属主题
        const metaHtml = isMomentum && fund.theme
          ? `${escapeHtml(fund.code)} · ${escapeHtml(fund.theme)}`
          : `${escapeHtml(fund.code)} · ${escapeHtml(fund.type)}`;

        // 动量榜显示 "动量" 标签
        const labelHtml = isMomentum
          ? `<div class="fund-return ${returnClass}">${valueStr}<span class="momentum-label">动量</span></div>`
          : `<div class="fund-return ${returnClass}">${valueStr}</div>`;

        return `
          <div class="fund-card">
            ${rankHtml}
            <div class="fund-info">
              <div class="fund-name">${escapeHtml(fund.name)}</div>
              <div class="fund-meta">${metaHtml}</div>
            </div>
            ${labelHtml}
          </div>
        `;
      })
      .join("");
```

- [ ] **Step 3: 更新 `style.css` — 动量Tab和动量标签样式**

在 `.overall-tab.active` 样式块之后添加：

```css
.momentum-tab {
  font-weight: 600;
  border-color: #9f7aea;
  color: #6b46c1;
  background: #faf5ff;
}
.momentum-tab.active {
  background: #805ad5;
  color: #fff;
  border-color: #805ad5;
}

.momentum-label {
  display: block;
  font-size: 10px;
  font-weight: 500;
  color: #805ad5;
  text-align: right;
  margin-top: 1px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
```

同时让 `.fund-return` 支持内部多行布局：

```css
.fund-return {
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
  text-align: right;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
```

- [ ] **Step 4: Commit**

```bash
git add index.html script.js style.css
git commit -m "feat: add momentum ranking tab to frontend

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 端到端验证

**Files:**
- Test run: `python cli.py update`

- [ ] **Step 1: 运行脚本，验证数据产出**

```bash
cd /Users/yuechu/MY/JijinPH && python cli.py update
```

检查输出：
- 终端显示 "交易日: ...(周五) ~ ...(周四)"
- 终端显示 "🚀 动量总榜 Top5（跨主题）"
- `data/latest.json` 包含 `momentumRanking` 字段
- 每只基金包含 `momentumScore` 和 `returns`（含 1w/2w/4w/12w）

- [ ] **Step 2: 验证 JSON 数据结构**

```bash
python3 -c "
import json
with open('data/latest.json') as f:
    data = json.load(f)
print('week:', data['week'])
print('momentumRanking count:', len(data.get('momentumRanking', [])))
print('Top 3 momentum:')
for fund in data.get('momentumRanking', [])[:3]:
    print(f'  {fund[\"code\"]} {fund[\"name\"]} [{fund[\"theme\"]}] score={fund[\"momentumScore\"]}')
# 检查主题内基金是否有 returns 字段
for theme in data['themes'][:1]:
    for fund in theme['funds'][:1]:
        print(f'Sample fund returns: {fund.get(\"returns\")}')
"
```

预期：week 格式为 `YYYY-MM-DD ~ YYYY-MM-DD`, momentumRanking 有数据, returns 含 4 个周期。

- [ ] **Step 3: 验证前端渲染**

```bash
python3 -m http.server 8080 --directory /Users/yuechu/MY/JijinPH &
echo "打开 http://localhost:8080 检查动量榜Tab是否显示"
```

打开浏览器，确认：
- "🚀 动量榜"Tab 出现在最左侧
- 点击后显示跨主题动量排名
- 每张卡片显示名称、代码、所属主题、动量得分

- [ ] **Step 4: Commit（如有微调）**

```bash
git add -A
git commit -m "chore: final adjustments after e2e verification

Co-Authored-By: Claude <noreply@anthropic.com>"
```
