(async function () {
  const tabBar = document.getElementById("tab-bar");
  const fundList = document.getElementById("fund-list");
  const weekRange = document.getElementById("week-range");
  const updateTime = document.getElementById("update-time");
  const weekSelect = document.getElementById("week-select");

  let data = null;
  let activeThemeIndex = -1;  // -1 = 总榜, 0..N = 各主题
  let availableWeeks = [];

  // ===== Load Week List =====
  async function loadManifest() {
    try {
      const resp = await fetch("data/manifest.json");
      if (!resp.ok) return;
      const manifest = await resp.json();
      availableWeeks = manifest.weeks || [];
      // 填充下拉框
      weekSelect.innerHTML = '<option value="latest">📅 最新一周</option>';
      availableWeeks.forEach((w, i) => {
        const selected = i === availableWeeks.length - 1 ? " selected" : "";
        weekSelect.innerHTML += `<option value="${w.file}">${w.week}</option>`;
      });
      // 默认选最新
      if (availableWeeks.length > 0) {
        weekSelect.value = "latest";
      }
    } catch (err) {
      console.warn("加载周列表失败，仅支持最新数据:", err);
    }
  }

  // ===== Fetch Data =====
  async function loadData(source) {
    const url = source === "latest" ? "data/latest.json" : `data/weekly/${source}`;
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
      if (!data || !data.themes || !data.week) {
        throw new Error("数据格式错误");
      }
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

  // ===== Build Combined Ranking (dedup across all themes) =====
  function buildOverallRanking() {
    const seen = new Set();
    const all = [];
    data.themes.forEach((theme) => {
      theme.funds.forEach((fund) => {
        if (!seen.has(fund.code)) {
          seen.add(fund.code);
          all.push({ ...fund });
        }
      });
    });
    all.sort((a, b) => b.weeklyReturn - a.weeklyReturn);
    return all.slice(0, 10); // 总榜取前10
  }

  // ===== Render Tab Bar =====
  function renderTabs() {
    tabBar.innerHTML = "";

    // 总榜按钮 (index = -1)
    const overallBtn = document.createElement("button");
    overallBtn.className = "tab-btn overall-tab";
    overallBtn.setAttribute("role", "tab");
    overallBtn.setAttribute("aria-selected", activeThemeIndex === -1 ? "true" : "false");
    if (activeThemeIndex === -1) overallBtn.classList.add("active");
    overallBtn.textContent = "🏆 总榜";
    overallBtn.addEventListener("click", () => {
      activeThemeIndex = -1;
      renderTabs();
      renderFunds();
    });
    tabBar.appendChild(overallBtn);

    // 各主题按钮 (index = 0..N)
    data.themes.forEach((theme, index) => {
      const btn = document.createElement("button");
      btn.className = "tab-btn";
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", index === activeThemeIndex ? "true" : "false");
      if (index === activeThemeIndex) btn.classList.add("active");
      btn.textContent = `${theme.name} (${theme.funds.length})`;
      btn.addEventListener("click", () => {
        activeThemeIndex = index;
        renderTabs();
        renderFunds();
      });
      tabBar.appendChild(btn);
    });
    fundList.setAttribute("role", "tabpanel");
    fundList.setAttribute("aria-label", "基金列表");
  }

  // ===== Render Fund Cards =====
  function renderFunds() {
    let funds;

    if (activeThemeIndex === -1) {
      // 总榜：合并所有主题，去重，取涨幅前10
      funds = buildOverallRanking();
    } else {
      if (activeThemeIndex >= data.themes.length) {
        activeThemeIndex = 0;
      }
      const theme = data.themes[activeThemeIndex];
      if (!theme || !theme.funds.length) {
        fundList.innerHTML =
          '<div class="empty-state">该板块暂无匹配基金</div>';
        return;
      }
      funds = theme.funds;
    }

    const medals = ["gold", "silver", "bronze"];
    const medalEmoji = ["🥇", "🥈", "🥉"];

    fundList.innerHTML = funds
      .filter((fund) => fund.weeklyReturn != null && !isNaN(fund.weeklyReturn))
      .map((fund, i) => {
        const medalClass = i < 3 ? medals[i] : "";
        const returnClass = fund.weeklyReturn >= 0 ? "up" : "down";
        const sign = fund.weeklyReturn >= 0 ? "+" : "";

        let rankHtml;
        if (i < 3) {
          rankHtml = `<div class="fund-rank ${medalClass}">${medalEmoji[i]}</div>`;
        } else {
          rankHtml = `<div class="fund-rank">${i + 1}</div>`;
        }

        return `
          <div class="fund-card">
            ${rankHtml}
            <div class="fund-info">
              <div class="fund-name">${escapeHtml(fund.name)}</div>
              <div class="fund-meta">${escapeHtml(fund.code)} · ${escapeHtml(fund.type)}</div>
            </div>
            <div class="fund-return ${returnClass}">${sign}${fund.weeklyReturn.toFixed(2)}%</div>
          </div>
        `;
      })
      .join("");
  }

  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ===== Week Selector Handler =====
  weekSelect.addEventListener("change", async () => {
    const source = weekSelect.value;
    activeThemeIndex = 0;
    fundList.innerHTML = '<div class="loading">加载中...</div>';
    const ok = await loadData(source);
    if (!ok) return;
    renderHeader();
    renderTabs();
    renderFunds();
  });

  // ===== Run =====
  await loadManifest();
  const ok = await loadData("latest");
  if (!ok) return;

  renderHeader();
  renderTabs();
  renderFunds();
})();
