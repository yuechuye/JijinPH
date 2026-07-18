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
