# 基金周涨幅榜 — 设计方案

## 概述

每周计算各投资主题板块中涨幅最高的热门基金，通过 CLI 更新数据，网站托管于 GitHub Pages 展示。

## 技术选型

- **CLI**：Python + AKShare（获取公募基金净值/涨幅数据）
- **网站**：纯静态 HTML/CSS/JS，托管于 GitHub Pages
- **配置**：YAML 文件定义主题与关键词映射
- **数据格式**：JSON，存储在仓库的 `data/weekly/` 目录下

## 架构

```
用户周末运行 CLI
       │
       ▼
  cli.py (Python)
       │
       ├── AKShare API ──→ 获取全市场基金净值/周涨幅
       │
       ├── config/themes.yaml ──→ 关键词匹配归类 + 排序
       │
       └── 输出 data/weekly/<date>.json
              │
       git commit & push
              │
              ▼
       GitHub Pages
              │
       index.html ← fetch JSON → 渲染榜单
```

## 数据模型

```json
{
  "week": "2026-07-13 ~ 2026-07-19",
  "updatedAt": "2026-07-19T12:00:00",
  "themes": [
    {
      "name": "新能源",
      "funds": [
        {
          "code": "400015",
          "name": "东方新能源汽车混合",
          "weeklyReturn": 5.23,
          "type": "混合型"
        }
      ]
    }
  ]
}
```

## CLI 工具设计 (`cli.py`)

**命令**：`python cli.py update`

**流程**：
1. 读取 `config/themes.yaml`
2. 通过 AKShare 获取全市场基金净值数据，计算最近一周（上周一至周五）的累计涨幅
3. 按关键词匹配基金名称，将基金归入各主题（同一基金可属于多个主题，取决于名称匹配哪些关键词）
4. 每主题取周涨幅 Top N（默认 5，可在配置中调整）
5. 生成 `data/weekly/YYYY-MM-DD.json` 和 `data/latest.json`（网站直接读取的后一份）
6. `git add → git commit → git push`
7. 终端打印摘要

**配置文件 `config/themes.yaml`**：

```yaml
topN: 5
themes:
  - name: 新能源
    keywords: [光伏, 新能源, 锂电, 储能, 电池, 电动汽车]
  - name: 半导体
    keywords: [半导体, 芯片, 集成电路]
  - name: 消费
    keywords: [消费, 白酒, 食品饮料, 家电]
  # ... 更多主题
```

## 网站设计 (`index.html`)

单页应用，结构：

- **顶部**：标题 "🔥 基金周涨幅榜" + 日期范围
- **标签栏**：主题 Tab 切换，横向排列，移动端可滚动
- **基金卡片列表**：前三名有金银铜牌标识，涨幅红涨绿跌
- **数据加载**：CLI 更新时同时生成 `data/latest.json`（复制到网站根目录），网站直接 fetch 这一个文件，无需扫描目录

### 交互

- 默认展示第一个主题
- 点击标签切换到对应主题的基金列表
- 纯 CSS 实现 Tab 切换（或最少 JS）

### 响应式

- 桌面端：标签水平排列，卡片居中最大宽度 800px
- 移动端：标签横向滚动，卡片单列全宽

## 文件结构

```
/Users/yuechu/MY/JijinPH/
├── index.html              # 网站主页
├── style.css               # 样式
├── script.js               # 前端逻辑
├── cli.py                  # CLI 入口
├── config/
│   └── themes.yaml         # 主题配置
├── data/
│   ├── latest.json          # 始终指向最新周数据
│   └── weekly/
│       └── 2026-07-19.json  # 每周数据（按日期归档）
└── requirements.txt        # Python 依赖
```

## 工作流

1. 每周末运行 `python cli.py update`
2. CLI 拉取最新数据、生成 JSON、自动 git commit & push
3. GitHub Pages 自动部署更新
4. 用户访问网站看到最新一周的涨幅榜
