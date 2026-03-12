/* ═══════════════════════════════════════════════
   策略信号交易系统 — 终端界面逻辑
   ═══════════════════════════════════════════════ */
'use strict';

const state = {
  accounts: [],
  signals: [],
  aggregator: { min_strength: 0.3 },
  strategy: { symbols: [], default_order_type: 'market', quantity_per_signal: 0.01 },
  risk: { dry_run: false, reverse_close: true, allow_add_position: false, tp_sl: { enabled: true, default_sl_pct: 0.02, default_tp_pct: 0.03, use_signal_levels: true }, max_single_order_pct: 0.5, max_position_pct: 0.2, max_total_exposure_pct: 3.0, max_daily_trades: 100 },
  webhook: { secret: '', ttl: 300 },
  scheduler: { running: false, interval: 60, total_runs: 0, total_errors: 0 },
  queue: { queue_size: 0, total_received: 0, ttl: 300 },
  positionsData: [],
  totalPositions: 0,
  totalOrders: 0,
  lastRun: '--',
};

const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);
const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

function ts() {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2,'0')).join(':');
}

// ─── 系统时钟 ──────────────────────────────────
function tickClock() {
  $('sys-time').textContent = ts();
}
setInterval(tickClock, 1000);
tickClock();

// ─── 终端日志 ──────────────────────────────────
let logCount = 0;

function log(tag, text, color = '') {
  const area = $('log-area');
  const el = document.createElement('div');
  el.className = 'log-line';
  const tagClass = tag.toLowerCase();
  el.innerHTML =
    `<span class="log-time">${ts()}</span>` +
    `<span class="log-tag ${tagClass}">${tag}</span>` +
    `<span class="log-text ${color}">${text}</span>`;
  area.appendChild(el);
  logCount++;
  $('dash-status').textContent = `${logCount} 行 · 最近更新: ${ts()}`;

  const scroll = $('log-scroll');
  requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
}

$('btn-clear-log').addEventListener('click', () => {
  $('log-area').innerHTML = '';
  logCount = 0;
  $('dash-status').textContent = '0 行 · 最近更新: ' + ts();
  fetch('/api/logs/clear', { method: 'POST' }).catch(() => {});
  log('系统', '日志已清空', 'dim');
});

// ─── 后端日志解析 ────────────────────────────────
function _parseLogTag(line) {
  if (line.startsWith('[PA+MACD'))  return '信号源';
  if (line.startsWith('[AlphaFactor')) return '信号源';
  if (line.startsWith('[InlineCode')) return '信号源';
  if (line.startsWith('[风控]'))     return '风控';
  if (line.startsWith('[Executor]') || line.startsWith('[Hyperliquid]')) return '执行器';
  if (line.startsWith('[DryRun]'))   return '执行器';
  if (line.startsWith('[主流程]'))   return '策略';
  if (line.startsWith('[webhook]'))  return 'webhook';
  return '系统';
}

function _parseLogColor(line) {
  if (line.includes('拒绝') || line.includes('失败') || line.includes('错误')) return 'red';
  if (line.includes('跳过') || line.includes('不重复')) return 'yellow';
  if (line.includes('平仓') || line.includes('反向信号')) return 'yellow';
  if (line.includes('削减')) return 'yellow';
  if (line.includes('已成交') || line.includes('成功')) return 'green';
  if (line.includes('LONG') || line.includes('做多')) return 'green';
  if (line.includes('SHORT') || line.includes('做空')) return 'red';
  if (line.includes('NEUTRAL') || line.includes('无信号') || line.includes('无待执行')) return 'dim';
  return '';
}

// ─── 仪表盘更新 ────────────────────────────────
function updateDash() {
  $('s-accounts').textContent = state.accounts.length;
  $('s-signals').textContent = state.signals.length;
  const symCount = (state.strategy.symbols || []).length;
  $('s-symbols').textContent = symCount;
  const isDry = state.risk.dry_run;
  const modeEl = $('s-mode');
  modeEl.textContent = isDry ? '试运行' : '实盘';
  modeEl.className = 'stat-val ' + (isDry ? 'yellow' : 'green');

  // 风控
  $('v-max-order').textContent = state.risk.max_single_order_pct ?? 0.1;
  $('v-max-daily').textContent = state.risk.max_daily_trades ?? 100;
  const dryEl = $('v-dryrun');
  dryEl.textContent = isDry ? '是' : '否';
  dryEl.className = 'v ' + (isDry ? 'yellow' : 'green');
  $('v-risk-status').textContent = isDry ? '试运行' : '运行中';
  $('v-risk-status').className = 'v ' + (isDry ? 'yellow' : 'green');

  // 信号源
  $('v-src-count').textContent = state.signals.length;
  $('v-min-str').textContent = state.aggregator.min_strength ?? 0.3;
  const oList = $('oracle-list');
  if (state.signals.length) {
    oList.innerHTML = state.signals.map(s => {
      const acc = s.account_id || '按权重分配';
      return `<div class="sub-item"><span class="si-id">${esc(s.id)}</span><span class="si-val">权重:${s.weight} → ${esc(acc)}</span></div>`;
    }).join('');
  } else {
    oList.innerHTML = '<div class="empty-hint">暂无信号源</div>';
  }

  // 策略
  const orderTypeMap = { limit: '限价', market: '市价' };
  $('v-order-type').textContent = orderTypeMap[state.strategy.default_order_type] || state.strategy.default_order_type;
  $('v-max-pos').textContent = state.risk.max_position_pct ?? 0.2;
  $('v-sym-count').textContent = symCount;
  const pSyms = $('prophet-symbols');
  if (symCount) {
    pSyms.innerHTML = state.strategy.symbols.map(s =>
      `<div class="sub-item"><span class="si-id">${esc(s)}</span></div>`
    ).join('');
  } else {
    pSyms.innerHTML = '<div class="empty-hint">暂无标的</div>';
  }

  // 执行器
  $('v-total-orders').textContent = state.totalOrders;
  $('v-last-run').textContent = state.lastRun;

  // 分配器
  const dBody = $('diversifier-body');
  if (state.accounts.length) {
    const maxW = Math.max(...state.accounts.map(a => a.weight || 0), 0.01);
    const brokerLabel = { sim: '模拟', binance_futures: '币安', hyperliquid: 'HL' };
    dBody.innerHTML = state.accounts.map(a => {
      const pct = Math.round(((a.weight || 0) / maxW) * 100);
      const on = a.enabled !== false;
      const bk = brokerLabel[a.broker] || a.broker;
      return `<div class="acc-bar">
        <span class="acc-bar-status ${on ? 'on' : 'off'}"></span>
        <span class="acc-bar-id">${esc(a.id)}</span>
        <span class="acc-bar-name">${esc(a.name)} <span style="color:var(--dim)">[${bk}]</span></span>
        <span class="acc-bar-weight">${a.weight}</span>
        <span class="acc-bar-fill"><span class="acc-bar-fill-inner" style="width:${pct}%"></span></span>
      </div>`;
    }).join('');
  } else {
    dBody.innerHTML = '<div class="empty-hint">暂无账号</div>';
  }

  // Webhook 队列
  $('v-queue-size').textContent = state.queue.queue_size;
  $('v-total-received').textContent = state.queue.total_received;
  $('v-queue-ttl').textContent = (state.queue.ttl || state.webhook.ttl || 300) + 's';

  // 调度器
  const schedOn = state.scheduler.running;
  const statusEl = $('v-sched-status');
  statusEl.textContent = schedOn ? '运行中' : '已停止';
  statusEl.className = 'v ' + (schedOn ? 'green' : 'red');
  $('v-sched-interval').textContent = state.scheduler.interval + 's';
  $('v-sched-runs').textContent = state.scheduler.total_runs;
  $('v-sched-errors').textContent = state.scheduler.total_errors;

  // 顶栏调度器指示
  const dot = $('sched-dot');
  const label = $('sched-label');
  dot.className = 'sched-dot' + (schedOn ? ' active' : '');
  label.className = 'sched-label' + (schedOn ? ' active' : '');
  label.textContent = schedOn ? `调度器: ${state.scheduler.interval}s` : '调度器: 停止';

  // 持仓统计
  $('s-positions').textContent = state.totalPositions;
  renderPositions();
}

// ─── 持仓渲染 ────────────────────────────────
function renderPositions() {
  const body = $('positions-body');
  const data = state.positionsData;
  if (!data || !data.length) {
    body.innerHTML = '<div class="empty-hint">点击刷新查询持仓</div>';
    return;
  }

  const brokerLabel = { sim: '模拟', binance_futures: '币安合约', hyperliquid: 'Hyperliquid' };
  let html = '';
  let totalPos = 0;

  for (const acc of data) {
    const bk = brokerLabel[acc.broker] || acc.broker;
    let balStr = '';
    if (acc.balance) {
      const b = acc.balance;
      if (b.available !== undefined) {
        balStr = `可用: ${Number(b.available).toFixed(2)} USDT`;
      } else if (b.USDT) {
        balStr = `可用: ${Number(b.USDT.available).toFixed(2)} USDT`;
      } else {
        const keys = Object.keys(b);
        if (keys.length) {
          const first = keys[0];
          const val = typeof b[first] === 'object' ? b[first].available ?? b[first].balance : b[first];
          balStr = `${first}: ${Number(val).toFixed(2)}`;
        }
      }
    }

    html += `<div class="pos-account-head">
      <span class="pos-acc-name">${esc(acc.name || acc.id)}</span>
      <span class="pos-acc-broker">[${bk}]</span>
      <span class="pos-acc-balance">${esc(balStr)}</span>
    </div>`;

    if (acc.error) {
      html += `<div style="color:var(--red);font-size:10px;padding:2px 0">${esc(acc.error)}</div>`;
    }

    const positions = acc.positions || [];
    totalPos += positions.length;

    if (positions.length === 0) {
      html += '<div class="empty-hint" style="padding:4px 0">无持仓</div>';
    } else {
      html += `<table class="pos-table"><thead><tr>
        <th>标的</th><th>方向</th><th>数量</th><th>开仓价</th><th>未实现盈亏</th><th>杠杆</th>
      </tr></thead><tbody>`;
      for (const p of positions) {
        const dirClass = p.side === 'LONG' ? 'pos-long' : 'pos-short';
        const dirText = p.side === 'LONG' ? '多' : '空';
        const pnl = Number(p.unrealized_pnl || 0);
        const pnlClass = pnl >= 0 ? 'pos-pnl-plus' : 'pos-pnl-minus';
        const pnlStr = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
        html += `<tr>
          <td style="color:var(--bright)">${esc(p.symbol)}</td>
          <td class="${dirClass}">${dirText}</td>
          <td>${p.size}</td>
          <td>${Number(p.entry_price || 0).toFixed(2)}</td>
          <td class="${pnlClass}">${pnlStr}</td>
          <td>${p.leverage || '--'}x</td>
        </tr>`;
      }
      html += '</tbody></table>';
    }
  }

  state.totalPositions = totalPos;
  $('s-positions').textContent = totalPos;
  body.innerHTML = html;
}

async function fetchPositions() {
  try {
    const res = await fetch('/api/positions');
    const data = await res.json();
    if (data.error) {
      log('持仓', `查询失败: ${data.error}`, 'red');
      return;
    }
    state.positionsData = data.accounts || [];
    renderPositions();
  } catch (err) {
    log('持仓', `网络错误: ${err.message}`, 'red');
  }
}

$('btn-refresh-pos').addEventListener('click', () => {
  log('持仓', '正在查询持仓…', 'yellow');
  fetchPositions().then(() => {
    const total = state.totalPositions;
    log('持仓', `查询完成 — ${state.positionsData.length} 个账号, ${total} 个持仓`, total > 0 ? 'yellow' : 'dim');
  });
});

// ─── 配置面板 ──────────────────────────────────
function openConfig() {
  $('config-overlay').classList.remove('hidden');
  renderCfgAccounts();
  renderCfgSignals();
  fillCfgStrategy();
  fillCfgWebhook();
}

function fillCfgWebhook() {
  $('cfg-webhook-secret').value = state.webhook.secret || '';
  $('cfg-webhook-ttl').value = state.webhook.ttl || 300;
  $('cfg-sched-interval').value = state.webhook.scheduler_interval || state.scheduler.interval || 60;
}

function closeConfig() {
  $('config-overlay').classList.add('hidden');
}

$('btn-config').addEventListener('click', openConfig);
$('btn-config-close').addEventListener('click', closeConfig);
$('cfg-cancel').addEventListener('click', closeConfig);

// Tab 切换
$$('.cfg-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.cfg-tab').forEach(t => t.classList.remove('active'));
    $$('.cfg-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $('cfg-' + btn.dataset.cfg).classList.add('active');
  });
});

// 渲染配置表-账号
function renderCfgAccounts() {
  const tbody = $('cfg-accounts-tbody');
  tbody.innerHTML = '';
  $('cfg-accounts-empty').classList.toggle('hidden', state.accounts.length > 0);
  $('cfg-accounts-table').parentElement.classList.toggle('hidden', state.accounts.length === 0);

  const brokerOpts = [
    { v: 'sim', t: '模拟' },
    { v: 'binance_futures', t: '币安合约' },
    { v: 'hyperliquid', t: 'Hyperliquid' },
  ];
  const brokerSelect = (cur, i) => brokerOpts.map(o =>
    `<option value="${o.v}"${cur===o.v?' selected':''}>${o.t}</option>`
  ).join('');

  state.accounts.forEach((a, i) => {
    const isReal = a.broker !== 'sim';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input class="cell-input" type="text" value="${esc(a.id)}" data-f="id" data-i="${i}" /></td>
      <td><input class="cell-input" type="text" value="${esc(a.name)}" data-f="name" data-i="${i}" /></td>
      <td><select class="cell-input" data-f="broker" data-i="${i}">
        ${brokerSelect(a.broker, i)}
      </select></td>
      <td><input class="cell-input" type="number" value="${a.weight}" min="0" max="1" step="0.1" data-f="weight" data-i="${i}" style="max-width:60px" /></td>
      <td><input class="cell-input" type="password" value="${esc(a.api_key || '')}" data-f="api_key" data-i="${i}" placeholder="${isReal?'必填':'选填'}" style="max-width:100px" /></td>
      <td><input class="cell-input" type="password" value="${esc(a.api_secret || '')}" data-f="api_secret" data-i="${i}" placeholder="${isReal?'必填':'选填'}" style="max-width:100px" /></td>
      <td><select class="cell-input" data-f="enabled" data-i="${i}" style="max-width:60px">
        <option value="true"${a.enabled!==false?' selected':''}>启用</option>
        <option value="false"${a.enabled===false?' selected':''}>停用</option>
      </select></td>
      <td><button class="t-btn-sm red" data-action="del-acc" data-i="${i}">删除</button></td>`;
    tbody.appendChild(tr);
  });
}

// 渲染配置表-信号源（新版卡片列表）
function renderCfgSignals() {
  const list = $('cfg-signals-list');
  list.innerHTML = '';
  $('cfg-signals-empty').classList.toggle('hidden', state.signals.length > 0);

  state.signals.forEach((s, i) => {
    const isCode = s.type === 'inline_code';
    const isFactor = s.type === 'alpha_factor';
    const typeLabel = isCode ? 'CODE' : isFactor ? 'FACTOR' : (s.type || 'SIG').toUpperCase();
    const typeClass = isCode ? 'code' : isFactor ? 'factor' : 'code';
    const sym = s.symbol || '--';
    const interval = s.interval || '--';
    const info = isFactor
      ? `${sym} · ${interval} · 因子: ${s.factor_name || '--'}`
      : isCode
        ? `${sym} · ${interval} · ${(s.code || '').split('\\n').length || 0} 行代码`
        : `权重: ${s.weight}`;

    const card = document.createElement('div');
    card.className = 'sig-card';
    card.innerHTML = `
      <span class="sig-card-type ${typeClass}">${typeLabel}</span>
      <span class="sig-card-id">${esc(s.id)}</span>
      <span class="sig-card-info">${esc(info)}</span>
      <div class="sig-card-actions">
        <button class="t-btn-sm green" data-action="edit-sig" data-i="${i}">编辑</button>
        <button class="t-btn-sm red" data-action="del-sig" data-i="${i}">删除</button>
      </div>`;
    list.appendChild(card);
  });

  $('cfg-min-strength').value = state.aggregator.min_strength ?? 0.3;
}

function fillCfgStrategy() {
  $('cfg-symbols').value = (state.strategy.symbols || []).join('\n');
  $('cfg-order-type').value = state.strategy.default_order_type || 'market';
  $('cfg-qty-per-signal').value = state.strategy.quantity_per_signal ?? 0.01;
  $('cfg-max-pos').value = state.risk.max_position_pct ?? 0.2;
  $('cfg-max-order').value = state.risk.max_single_order_pct ?? 0.5;
  $('cfg-max-daily').value = state.risk.max_daily_trades ?? 100;
  $('cfg-dryrun').checked = !!state.risk.dry_run;
}

// 从配置表单同步回 state
function syncCfgToState() {
  $$('#cfg-accounts-tbody tr').forEach((tr, i) => {
    if (!state.accounts[i]) return;
    tr.querySelectorAll('[data-f]').forEach(el => {
      const f = el.dataset.f;
      let v = el.value;
      if (f === 'weight') v = parseFloat(v) || 0;
      if (f === 'enabled') v = v === 'true';
      state.accounts[i][f] = v;
    });
  });
  // 信号源现在通过编辑器管理，state.signals 已经是最新的
  state.aggregator.min_strength = parseFloat($('cfg-min-strength').value) || 0.3;
  const raw = $('cfg-symbols').value.trim();
  state.strategy.symbols = raw ? raw.split('\n').map(s => s.trim()).filter(Boolean) : [];
  state.strategy.default_order_type = $('cfg-order-type').value;
  state.strategy.quantity_per_signal = parseFloat($('cfg-qty-per-signal').value) || 0.01;
  state.risk.max_position_pct = parseFloat($('cfg-max-pos').value) || 0.2;
  state.risk.max_single_order_pct = parseFloat($('cfg-max-order').value) || 0.5;
  state.risk.max_daily_trades = parseInt($('cfg-max-daily').value) || 100;
  state.risk.dry_run = $('cfg-dryrun').checked;
  state.webhook.secret = $('cfg-webhook-secret').value;
  state.webhook.ttl = parseInt($('cfg-webhook-ttl').value) || 300;
  const schedInterval = parseInt($('cfg-sched-interval')?.value) || 60;
  state.webhook.scheduler_interval = schedInterval;
  state.scheduler.interval = schedInterval;
}

// 添加/删除
$('cfg-add-account').addEventListener('click', () => {
  syncCfgToState();
  state.accounts.push({ id: `acc_${Date.now() % 100000}`, name: '新账号', broker: 'sim', weight: 0.5, enabled: true, api_key: '', api_secret: '', testnet: true });
  renderCfgAccounts();
  log('系统', `已添加账号 → 当前共 ${state.accounts.length} 个`, 'green');
});

$('cfg-add-signal').addEventListener('click', () => {
  syncCfgToState();
  openSignalEditor(-1);
});

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const i = parseInt(btn.dataset.i);
  if (btn.dataset.action === 'del-acc') {
    syncCfgToState();
    const id = state.accounts[i]?.id || '?';
    state.accounts.splice(i, 1);
    renderCfgAccounts();
    log('系统', `已删除账号: ${id}`, 'dim');
  }
  if (btn.dataset.action === 'del-sig') {
    syncCfgToState();
    const id = state.signals[i]?.id || '?';
    state.signals.splice(i, 1);
    renderCfgSignals();
    log('系统', `已删除信号源: ${id}`, 'dim');
  }
  if (btn.dataset.action === 'edit-sig') {
    openSignalEditor(i);
  }
});

// ─── 信号源编辑器 ────────────────────────────────
let seEditIndex = -1;
let seFactorsCache = null;

const SE_DEFAULT_CODE = `# 在此粘贴你的策略代码
# 必须定义 calculate_factor(df) 函数
# df 包含列: open, high, low, close, volume
# 返回 pd.Series，系统自动做 z-score 标准化
#
# 示例：
# import pandas as pd
# import numpy as np
# def calculate_factor(df):
#     sma_fast = df["close"].rolling(5).mean()
#     sma_slow = df["close"].rolling(20).mean()
#     return sma_fast - sma_slow
`;

function openSignalEditor(index) {
  seEditIndex = index;
  const isNew = index < 0;
  $('se-title').textContent = isNew ? '新建信号源' : '编辑信号源';

  // 填充账号下拉
  const accSel = $('se-account');
  accSel.innerHTML = '<option value="">按权重分配</option>';
  state.accounts.forEach(a => {
    accSel.innerHTML += `<option value="${esc(a.id)}">${esc(a.id)}</option>`;
  });

  if (isNew) {
    $('se-id').value = `sig_${Date.now() % 100000}`;
    $('se-type').value = 'inline_code';
    $('se-symbol').value = 'BTC';
    $('se-interval').value = '1h';
    $('se-weight').value = '1.0';
    $('se-threshold').value = '1.0';
    $('se-direction').value = '1';
    $('se-account').value = '';
    $('se-code').value = SE_DEFAULT_CODE;
  } else {
    const s = state.signals[index];
    $('se-id').value = s.id || '';
    $('se-type').value = s.type || 'inline_code';
    $('se-symbol').value = s.symbol || 'BTC';
    $('se-interval').value = s.interval || '1h';
    $('se-weight').value = s.weight ?? 1.0;
    $('se-threshold').value = s.z_threshold ?? 1.0;
    $('se-direction').value = String(s.direction ?? 1);
    $('se-account').value = s.account_id || '';
    $('se-code').value = s.code || SE_DEFAULT_CODE;
    if (s.type === 'alpha_factor' && s.factor_name) {
      loadFactorsList().then(() => { $('se-factor-name').value = s.factor_name; });
    }
  }

  toggleSeType();
  $('se-result').innerHTML = '<div class="se-result-placeholder">点击"测试运行"查看最近 20 根 K 线的信号</div>';
  $('se-test-status').textContent = '';
  $('signal-editor').classList.remove('hidden');
}

function closeSignalEditor() {
  $('signal-editor').classList.add('hidden');
}

function toggleSeType() {
  const t = $('se-type').value;
  const codeSection = $('se-code-section');
  const codeArea = $('se-code');
  const factorRow = $('se-factor-row');

  if (t === 'alpha_factor') {
    codeSection.style.display = 'none';
    codeArea.style.display = 'none';
    factorRow.style.display = 'block';
    loadFactorsList();
  } else {
    codeSection.style.display = '';
    codeArea.style.display = '';
    factorRow.style.display = 'none';
  }
}

async function loadFactorsList() {
  if (seFactorsCache) {
    renderFactorSelect(seFactorsCache);
    return;
  }
  try {
    const res = await fetch('/api/factors');
    const data = await res.json();
    seFactorsCache = data.factors || [];
    renderFactorSelect(seFactorsCache);
  } catch (err) {
    $('se-factor-name').innerHTML = '<option value="">加载失败</option>';
  }
}

function renderFactorSelect(factors) {
  const sel = $('se-factor-name');
  sel.innerHTML = '';
  factors.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.factor_name;
    opt.textContent = `${f.factor_name} (Sharpe ${f.sharpe})`;
    opt.title = f.description;
    sel.appendChild(opt);
  });
}

$('se-type').addEventListener('change', toggleSeType);
$('se-close').addEventListener('click', closeSignalEditor);
$('se-cancel').addEventListener('click', closeSignalEditor);

// 测试运行
$('se-test').addEventListener('click', async () => {
  const statusEl = $('se-test-status');
  const resultEl = $('se-result');
  statusEl.textContent = '正在获取K线并计算…';
  statusEl.style.color = 'var(--yellow)';

  const payload = {
    type: $('se-type').value,
    symbol: $('se-symbol').value || 'BTC',
    interval: $('se-interval').value || '1h',
    z_threshold: parseFloat($('se-threshold').value) || 1.0,
    direction: parseInt($('se-direction').value) || 1,
    code: $('se-code').value,
    factor_name: $('se-factor-name').value,
  };

  try {
    const res = await fetch('/api/signal/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.error) {
      statusEl.textContent = '执行失败';
      statusEl.style.color = 'var(--red)';
      resultEl.innerHTML = `<div style="color:var(--red);white-space:pre-wrap;font-size:10px">${esc(data.error)}\n${esc(data.trace || '')}</div>`;
      return;
    }

    const sigCount = data.signal_count || 0;
    statusEl.textContent = sigCount > 0 ? `当前有 ${sigCount} 条信号` : '当前无信号（未超阈值）';
    statusEl.style.color = sigCount > 0 ? 'var(--green)' : 'var(--muted)';

    if (data.z_history && data.z_history.length) {
      let html = '<table><thead><tr><th>时间</th><th>z-score</th><th>信号</th></tr></thead><tbody>';
      const th = parseFloat($('se-threshold').value) || 1.0;
      let triggerCount = 0;
      data.z_history.forEach(row => {
        const z = row.z_score;
        const zClass = z > 0 ? 'z-pos' : z < 0 ? 'z-neg' : '';
        let sigHtml = '';
        if (row.signal === 'LONG') { sigHtml = '<span class="sig-long">多</span>'; triggerCount++; }
        else if (row.signal === 'SHORT') { sigHtml = '<span class="sig-short">空</span>'; triggerCount++; }
        const timeStr = row.time.replace('T', ' ').substring(5, 16);
        html += `<tr><td>${timeStr}</td><td class="${zClass}">${z >= 0 ? '+' : ''}${z.toFixed(4)}</td><td>${sigHtml}</td></tr>`;
      });
      html += '</tbody></table>';
      html += `<div style="padding:6px 0;color:var(--muted);font-size:9px">近 ${data.z_history.length} 根K线中 ${triggerCount} 次触发 (阈值 ±${th})</div>`;

      if (data.signals && data.signals.length) {
        html += '<div style="padding:4px 0;color:var(--green);font-size:10px;font-weight:600">当前信号:</div>';
        data.signals.forEach(s => {
          const dirClass = s.direction === 'LONG' ? 'sig-long' : 'sig-short';
          const dirLabel = s.direction === 'LONG' ? '多' : '空';
          html += `<div style="font-size:10px"><span class="${dirClass}">${dirLabel}</span> ${esc(s.symbol)} 强度=${s.strength} z=${s.extra?.z_score ?? '--'}</div>`;
        });
      }
      resultEl.innerHTML = html;
    } else {
      resultEl.innerHTML = '<div class="se-result-placeholder">无 z-score 数据</div>';
    }
  } catch (err) {
    statusEl.textContent = '网络错误';
    statusEl.style.color = 'var(--red)';
    resultEl.innerHTML = `<div style="color:var(--red)">${esc(err.message)}</div>`;
  }
});

// 保存信号源
$('se-save').addEventListener('click', () => {
  const id = $('se-id').value.trim();
  if (!id) { alert('请输入信号源 ID'); return; }

  const sigObj = {
    id: id,
    type: $('se-type').value,
    weight: parseFloat($('se-weight').value) || 1.0,
    account_id: $('se-account').value || null,
    symbol: $('se-symbol').value || 'BTC',
    interval: $('se-interval').value || '1h',
    z_threshold: parseFloat($('se-threshold').value) || 1.0,
    direction: parseInt($('se-direction').value) || 1,
  };

  if (sigObj.type === 'inline_code') {
    sigObj.code = $('se-code').value;
  } else if (sigObj.type === 'alpha_factor') {
    sigObj.factor_name = $('se-factor-name').value;
  }

  if (seEditIndex >= 0) {
    state.signals[seEditIndex] = sigObj;
    log('系统', `信号源已更新: ${id}`, 'cyan');
  } else {
    state.signals.push(sigObj);
    log('系统', `已添加信号源: ${id}`, 'cyan');
  }

  renderCfgSignals();
  closeSignalEditor();
  updateDash();
});

// Tab 键在代码编辑器中插入空格
$('se-code').addEventListener('keydown', e => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const ta = e.target;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    ta.value = ta.value.substring(0, start) + '    ' + ta.value.substring(end);
    ta.selectionStart = ta.selectionEnd = start + 4;
  }
});

// ESC 关闭
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (!$('signal-editor').classList.contains('hidden')) closeSignalEditor();
    else if (!$('config-overlay').classList.contains('hidden')) closeConfig();
  }
});

// ─── 保存 ──────────────────────────────────────
function getPayload() {
  return {
    accounts: state.accounts,
    signals: state.signals,
    aggregator: state.aggregator,
    strategy: state.strategy,
    risk: state.risk,
    webhook: state.webhook,
  };
}

async function doSave() {
  syncCfgToState();
  log('日志', '正在保存配置…');

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getPayload()),
    });
    const data = await res.json();
    if (data.ok) {
      log('日志', '配置保存成功 ✓', 'green');
      updateDash();
    } else {
      log('风控', `保存失败: ${data.error || '未知错误'}`, 'red');
    }
  } catch (err) {
    log('风控', `网络错误: ${err.message}`, 'red');
  }
}

$('btn-save').addEventListener('click', doSave);
$('cfg-save').addEventListener('click', async () => {
  await doSave();
  closeConfig();
});

// ─── 运行 ──────────────────────────────────────
$('btn-run').addEventListener('click', async () => {
  syncCfgToState();
  const btn = $('btn-run');
  btn.classList.add('loading');

  log('系统', '═══ 周期开始 ═══', 'bright');
  log('日志', '运行前保存配置…');

  try {
    const sr = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getPayload()),
    });
    const sd = await sr.json();
    if (!sd.ok) {
      log('风控', `保存失败: ${sd.error || ''}`, 'red');
      btn.classList.remove('loading');
      return;
    }
    log('日志', '配置已保存 ✓', 'green');

    log('信号源', `信号源数: ${state.signals.length} | 最小强度: ${state.aggregator.min_strength}`, 'cyan');
    state.signals.forEach(s => {
      const acc = s.account_id || '按权重分配';
      log('信号源', `  → ${s.id} (权重:${s.weight}) → ${acc}`, 'dim');
    });

    log('策略', `下单类型: ${state.strategy.default_order_type} | 标的: ${(state.strategy.symbols||[]).join(', ')}`, 'yellow');
    log('风控', `单笔上限: ${state.risk.max_single_order_pct} | 日上限: ${state.risk.max_daily_trades} | 试运行: ${state.risk.dry_run ? '是' : '否'}`, '');

    log('分配器', `账号数: ${state.accounts.length}`, '');
    state.accounts.forEach(a => {
      log('分配器', `  → ${a.id} [${a.broker}] 权重:${a.weight} ${a.enabled!==false ? '启用' : '停用'}`, 'dim');
    });

    log('执行器', '正在执行交易周期…', 'green');

    const rr = await fetch('/api/run', { method: 'POST' });
    const rd = await rr.json();
    if (rd.ok) {
      // 显示后端执行日志
      if (rd.logs && rd.logs.length) {
        rd.logs.forEach(line => {
          const tag = _parseLogTag(line);
          const color = _parseLogColor(line);
          log(tag, line, color);
        });
      }

      state.totalOrders += rd.order_count;
      state.lastRun = ts();
      log('执行器', `执行完成 ✓ — 生成 ${rd.order_count} 笔订单`, 'green');

      const rb = $('result-body');
      rb.innerHTML = `<div class="result-line success">+${rd.order_count} 笔订单 · ${ts()}</div>`;
      if (rd.order_ids && rd.order_ids.length) {
        rd.order_ids.forEach(id => {
          log('执行器', `  订单号: ${id}`, 'green');
          rb.innerHTML += `<div class="result-line" style="color:var(--text)">  → ${esc(id)}</div>`;
        });
      }

      if (rd.order_count === 0) {
        log('执行器', '本次无订单生成（请检查信号源与风控过滤）', 'dim');
      }
    } else {
      if (rd.logs && rd.logs.length) {
        rd.logs.forEach(line => {
          log(_parseLogTag(line), line, _parseLogColor(line));
        });
      }
      log('风控', `运行错误: ${rd.error || '未知错误'}`, 'red');
      $('result-body').innerHTML = `<div class="result-line error">错误: ${esc(rd.error || '未知错误')}</div>`;
    }
  } catch (err) {
    log('风控', `网络错误: ${err.message}`, 'red');
  } finally {
    log('系统', '═══ 周期结束 ═══', 'bright');
    btn.classList.remove('loading');
    updateDash();
    fetchPositions();
  }
});

// ─── 调度器控制 ────────────────────────────────
$('btn-sched-start').addEventListener('click', async () => {
  const interval = parseFloat($('cfg-sched-interval')?.value) || state.scheduler.interval || 60;
  log('调度器', `正在启动调度器 (间隔: ${interval}s)…`, 'green');
  try {
    const res = await fetch('/api/scheduler/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interval }),
    });
    const data = await res.json();
    if (data.ok) {
      Object.assign(state.scheduler, data.status);
      log('调度器', '调度器已启动 — 将自动执行交易周期', 'green');
      updateDash();
    }
  } catch (err) {
    log('风控', `调度器启动失败: ${err.message}`, 'red');
  }
});

$('btn-sched-stop').addEventListener('click', async () => {
  log('调度器', '正在停止调度器…', 'yellow');
  try {
    const res = await fetch('/api/scheduler/stop', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      Object.assign(state.scheduler, data.status);
      log('调度器', '调度器已停止', 'dim');
      updateDash();
    }
  } catch (err) {
    log('风控', `调度器停止失败: ${err.message}`, 'red');
  }
});

// ─── 定时轮询状态 ──────────────────────────────
async function pollStatus() {
  try {
    const [qRes, sRes] = await Promise.all([
      fetch('/api/webhook/status'),
      fetch('/api/scheduler/status'),
    ]);
    const qData = await qRes.json();
    const sData = await sRes.json();
    Object.assign(state.queue, qData);
    const prevRuns = state.scheduler.total_runs;
    Object.assign(state.scheduler, sData);
    if (sData.total_runs > prevRuns && sData.last_result) {
      const r = sData.last_result;
      log('调度器', '═══ 自动执行周期 ═══', 'bright');
      if (r.logs && r.logs.length) {
        r.logs.forEach(line => {
          log(_parseLogTag(line), line, _parseLogColor(line));
        });
      }
      if (r.ok) {
        state.totalOrders += r.order_count;
        state.lastRun = ts();
        log('调度器', `自动执行完成 — ${r.order_count} 笔订单`, 'green');
        const rb = $('result-body');
        rb.innerHTML = `<div class="result-line success">[自动] +${r.order_count} 笔订单 · ${ts()}</div>`;
        fetchPositions();
      } else {
        log('调度器', `自动执行出错: ${r.error}`, 'red');
      }
    }
    updateDash();
  } catch (err) {
    console.warn('[pollStatus]', err);
  }
}

setInterval(pollStatus, 5000);
setInterval(fetchPositions, 30000);

// ─── Webhook 配置面板 ───────────────────────────
$('cfg-gen-secret').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/webhook/generate-secret', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      $('cfg-webhook-secret').value = data.secret;
      state.webhook.secret = data.secret;
      log('系统', 'Webhook 密钥已生成', 'green');
    }
  } catch (err) {
    log('风控', `密钥生成失败: ${err.message}`, 'red');
  }
});

// ─── 历史日志加载 ─────────────────────────────────
async function loadHistoryLogs() {
  try {
    const res = await fetch('/api/logs?limit=200');
    const data = await res.json();
    const records = data.logs || [];
    if (!records.length) return;
    log('系统', `── 历史日志 (${records.length} 条) ──`, 'dim');
    for (const r of records) {
      const tag = _parseLogTag(r.text);
      const color = _parseLogColor(r.text);
      const area = $('log-area');
      const el = document.createElement('div');
      el.className = 'log-line';
      const tagClass = tag.toLowerCase();
      el.innerHTML =
        `<span class="log-time">${r.ts.substring(11, 19)}</span>` +
        `<span class="log-tag ${tagClass}">${tag}</span>` +
        `<span class="log-text ${color}">${r.text}</span>`;
      area.appendChild(el);
      logCount++;
    }
    log('系统', '── 历史日志结束 ──', 'dim');
    const scroll = $('log-scroll');
    requestAnimationFrame(() => { scroll.scrollTop = scroll.scrollHeight; });
  } catch (err) {
    console.warn('[loadHistoryLogs]', err);
  }
}

// ─── 初始加载 ──────────────────────────────────
async function boot() {
  log('系统', '策略信号交易系统 v1.0 启动中…', 'green');
  log('系统', `启动时间: ${new Date().toLocaleString('zh-CN')}`, 'dim');

  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    if (data.error) {
      log('风控', `配置加载失败: ${data.error}`, 'red');
      return;
    }

    state.accounts   = data.accounts   || [];
    state.signals    = data.signals    || [];
    state.aggregator = data.aggregator || { min_strength: 0.3 };
    state.strategy   = data.strategy   || { symbols: [], default_order_type: 'market', quantity_per_signal: 0.01 };
    state.risk       = data.risk       || { dry_run: false, max_single_order_pct: 0.5, max_position_pct: 0.2, max_total_exposure_pct: 3.0, max_daily_trades: 100 };
    state.webhook    = data.webhook    || { secret: '', ttl: 300, scheduler_interval: 60 };
    state.scheduler.interval = state.webhook.scheduler_interval || 60;

    log('日志', `已加载 ${state.accounts.length} 个账号、${state.signals.length} 个信号源`, 'green');
    log('策略', `交易标的: ${(state.strategy.symbols||[]).join(', ') || '无'}`, 'yellow');
    log('风控', `试运行: ${state.risk.dry_run ? '是' : '否'} | 单笔上限: ${state.risk.max_single_order_pct}`, '');
    log('webhook', `Webhook 接收端点: POST /api/webhook | TTL: ${state.webhook.ttl}s`, 'cyan');
    log('webhook', state.webhook.secret ? 'Webhook 密钥已配置' : 'Webhook 无密钥（开放接收）', state.webhook.secret ? 'green' : 'yellow');

    state.accounts.forEach(a => {
      const status = a.enabled !== false ? '启用' : '停用';
      log('分配器', `账号 ${a.id} [${a.broker}] 权重:${a.weight} ${status}`, 'dim');
    });

    state.signals.forEach(s => {
      const acc = s.account_id || '按权重分配';
      log('信号源', `源 ${s.id} 权重:${s.weight} → ${acc}`, 'dim');
    });

    await loadHistoryLogs();
    await pollStatus();
    await fetchPositions();
    await fetchTrades();
    updateDash();
    log('系统', '系统就绪 — 等待指令', 'green');
    log('系统', '点击 [ 配置 ] 编辑参数，[ 运行 ] 执行交易', 'dim');
    log('系统', '外部策略可通过 POST /api/webhook 推送信号', 'dim');

  } catch (err) {
    log('风控', `启动失败: ${err.message}`, 'red');
  }
}

// ─── 交易历史 & 复盘 ────────────────────────────
async function fetchTrades() {
  try {
    const res = await fetch('/api/trades');
    const data = await res.json();
    if (data.error) return;

    const stats = data.stats || {};
    $('j-total').textContent = stats.total_trades || 0;
    const wr = stats.win_rate || 0;
    $('j-winrate').textContent = wr + '%';
    $('j-winrate').className = 'stat-val ' + (wr >= 50 ? 'green' : wr > 0 ? 'yellow' : '');
    const pnl = stats.total_pnl || 0;
    $('j-pnl').textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
    $('j-pnl').className = 'stat-val ' + (pnl >= 0 ? 'green' : 'red');
    $('j-open').textContent = stats.open_trades || 0;

    const body = $('trades-body');
    const records = data.records || [];
    if (!records.length) {
      body.innerHTML = '<div class="empty-hint">暂无交易记录</div>';
      return;
    }

    let html = '<table class="pos-table"><thead><tr><th>时间</th><th>类型</th><th>币种</th><th>方向</th><th>数量</th><th>价格</th><th>SL</th><th>TP</th><th>信号</th></tr></thead><tbody>';
    for (const r of records) {
      const typeLabel = r.type === 'open' ? '开仓' : '平仓';
      const typeClass = r.type === 'open' ? 'cyan' : 'yellow';
      const sideLabel = r.side === 'buy' ? '多' : '空';
      const sideClass = r.side === 'buy' ? 'pos-long' : 'pos-short';
      const sl = r.stop_loss ? r.stop_loss.toFixed(2) : '--';
      const tp = r.take_profit ? r.take_profit.toFixed(2) : '--';
      const sig = (r.signal_reasons || []).join(', ') || r.close_reason || '--';
      const price = r.price ? r.price.toFixed(2) : '--';
      const time = (r.time || '').substring(5, 16);
      html += `<tr>
        <td>${time}</td>
        <td style="color:var(--${typeClass})">${typeLabel}</td>
        <td style="color:var(--bright)">${esc(r.symbol)}</td>
        <td class="${sideClass}">${sideLabel}</td>
        <td>${r.quantity}</td>
        <td>${price}</td>
        <td>${sl}</td>
        <td>${tp}</td>
        <td style="font-size:9px;color:var(--muted)">${esc(sig)}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    body.innerHTML = html;
  } catch (err) {
    console.warn('[fetchTrades]', err);
  }
}

$('btn-refresh-trades').addEventListener('click', () => {
  fetchTrades();
});

boot();
