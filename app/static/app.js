/* Cüzdanım — PWA frontend (vanilla JS, no build step). */
(() => {
  'use strict';

  const API = '/api/v1';
  const APP_VERSION = '1.1.0'; // must match settings.APP_VERSION on the server
  const TOKEN_KEY = 'cuzdanim_access';
  const REFRESH_KEY = 'cuzdanim_refresh';
  const TABS = ['today', 'plan', 'recurring', 'tx', 'analytics', 'settings'];

  // ------------------------------------------------------------------------
  // i18n maps
  // ------------------------------------------------------------------------
  const CATEGORY_TR = {
    salary: 'Maaş', freelance: 'Serbest İş', investment: 'Yatırım', gift: 'Hediye', other_income: 'Diğer Gelir',
    food_dining: 'Yemek / Restoran', groceries: 'Market', transportation: 'Ulaşım', housing: 'Kira / Konut',
    utilities: 'Faturalar', healthcare: 'Sağlık', entertainment: 'Eğlence', shopping: 'Alışveriş',
    education: 'Eğitim', travel: 'Seyahat', insurance: 'Sigorta', savings_transfer: 'Birikim Transferi',
    debt_payment: 'Borç Ödemesi', subscriptions: 'Abonelikler', other_expense: 'Diğer Gider',
  };
  const CATEGORY_ICON = {
    salary: '💼', freelance: '🧑‍💻', investment: '📈', gift: '🎁', other_income: '➕',
    food_dining: '🍽️', groceries: '🛒', transportation: '🚌', housing: '🏠', utilities: '💡', healthcare: '🩺',
    entertainment: '🎬', shopping: '🛍️', education: '📚', travel: '✈️', insurance: '🛡️',
    savings_transfer: '🏦', debt_payment: '💳', subscriptions: '🔁', other_expense: '➖',
  };
  const INCOME_CATS = ['salary', 'freelance', 'investment', 'gift', 'other_income'];
  const EXPENSE_CATS = Object.keys(CATEGORY_TR).filter((c) => !INCOME_CATS.includes(c));
  const PAYMENT_TR = {
    cash: 'Nakit', credit_card: 'Kredi Kartı', debit_card: 'Banka Kartı',
    bank_transfer: 'Havale / EFT', mobile_payment: 'Mobil Ödeme', other: 'Diğer',
  };
  const MONTHS_TR = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
  const WEEKDAYS_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
  const STATUS_TR = {
    on_track: ['Yolunda', 'ok'], tight: ['Dikkat', 'warn'], over: ['Aşıldı', 'err'], no_income: ['Gelir yok', 'warn'],
  };

  // ------------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const moneyFmt = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', minimumFractionDigits: 2 });
  const money = (v) => moneyFmt.format(Number(v || 0));
  const pad = (n) => String(n).padStart(2, '0');
  const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const monthLabel = (d) => `${MONTHS_TR[d.getMonth()]} ${d.getFullYear()}`;
  const fmtDateTime = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const fmtTime = (iso) => { const d = new Date(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const fmtDayShort = (iso) => { const d = new Date(iso); return `${WEEKDAYS_TR[(d.getDay() + 6) % 7]} ${pad(d.getDate())}.${pad(d.getMonth() + 1)}`; };
  const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  let toastTimer;
  function toast(msg, isError = false) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.toggle('error', isError);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
  }

  // ------------------------------------------------------------------------
  // API client with automatic token refresh
  // ------------------------------------------------------------------------
  const tokens = {
    get access() { return localStorage.getItem(TOKEN_KEY); },
    get refresh() { return localStorage.getItem(REFRESH_KEY); },
    set(t) { localStorage.setItem(TOKEN_KEY, t.access_token); localStorage.setItem(REFRESH_KEY, t.refresh_token); },
    clear() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(REFRESH_KEY); },
  };

  async function refreshTokens() {
    if (!tokens.refresh) return false;
    const res = await fetch(`${API}/auth/refresh`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refresh }),
    });
    if (!res.ok) return false;
    tokens.set(await res.json());
    return true;
  }

  async function api(path, { method = 'GET', body, form, auth = true, retry = true } = {}) {
    const headers = {};
    if (auth && tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
    let payload;
    if (form) { payload = new URLSearchParams(form); headers['Content-Type'] = 'application/x-www-form-urlencoded'; }
    else if (body !== undefined) { payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }

    const res = await fetch(`${API}${path}`, { method, headers, body: payload });
    if (res.status === 401 && auth && retry && await refreshTokens()) {
      return api(path, { method, body, form, auth, retry: false });
    }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) { tokens.clear(); showAuth(); }
      let detail = typeof data.detail === 'string' ? data.detail : (data.errors?.[0]?.message || 'Bir hata oluştu.');
      if (res.status === 404 && detail === 'Not Found') {
        // The route doesn't exist on the server -> it is running an older build.
        detail = 'Sunucu eski sürümde çalışıyor. basla.bat penceresini kapatıp yeniden aç.';
        showVersionBanner('eski');
      }
      throw new Error(detail);
    }
    return data;
  }

  // ------------------------------------------------------------------------
  // Server/client version check — a stale server process is the #1 cause of
  // "Not Found" after an update, so say so in plain Turkish.
  // ------------------------------------------------------------------------
  function showVersionBanner(serverVersion) {
    const el = $('#version-banner');
    el.textContent = `⚠️ Sunucu ${serverVersion} sürümünde, uygulama ${APP_VERSION}. Çalışan basla.bat penceresini kapatıp yeniden aç (veri kaybolmaz).`;
    el.classList.remove('hidden');
  }
  async function checkServerVersion() {
    try {
      const res = await fetch('/health', { cache: 'no-store' });
      const h = await res.json();
      if (h.version && h.version !== APP_VERSION) showVersionBanner(h.version);
      else $('#version-banner').classList.add('hidden');
    } catch (_) { /* offline: nothing to compare */ }
  }

  // ------------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------------
  const state = {
    user: null,
    plan: null,
    periodType: 'monthly',
    charts: {},
    txPage: 1,
    txFilter: '',
    txTotalPages: 1,
    analyticsMonth: new Date(),
    installPrompt: null,
  };

  // ------------------------------------------------------------------------
  // Screens & tabs
  // ------------------------------------------------------------------------
  function showAuth() {
    $('#view-app').classList.add('hidden');
    $('#view-auth').classList.remove('hidden');
  }

  async function showApp() {
    $('#view-auth').classList.add('hidden');
    $('#view-app').classList.remove('hidden');
    const now = new Date();
    $('#today-label').textContent = `${pad(now.getDate())} ${MONTHS_TR[now.getMonth()]} ${now.getFullYear()}`;
    $('#me-name').textContent = state.user.full_name || 'Kullanıcı';
    $('#me-email').textContent = state.user.email;
    const initial = (location.hash || '#today').slice(1);
    switchTab(TABS.includes(initial) ? initial : 'today');
  }

  function switchTab(name) {
    $$('.tab').forEach((t) => t.classList.add('hidden'));
    $(`#tab-${name}`).classList.remove('hidden');
    $$('nav.tabbar button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    history.replaceState(null, '', `#${name}`);
    window.scrollTo({ top: 0 });
    ({
      today: loadToday, plan: loadPlan, recurring: loadRecurring,
      tx: () => loadTransactions(true), analytics: loadAnalytics, settings: loadSettings,
    })[name]();
  }

  // ------------------------------------------------------------------------
  // Auth
  // ------------------------------------------------------------------------
  $('#auth-tab-login').onclick = () => {
    $('#auth-tab-login').classList.add('active'); $('#auth-tab-signup').classList.remove('active');
    $('#form-login').classList.remove('hidden'); $('#form-signup').classList.add('hidden');
  };
  $('#auth-tab-signup').onclick = () => {
    $('#auth-tab-signup').classList.add('active'); $('#auth-tab-login').classList.remove('active');
    $('#form-signup').classList.remove('hidden'); $('#form-login').classList.add('hidden');
  };

  $('#form-login').onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      tokens.set(await api('/auth/login', { method: 'POST', auth: false, form: { username: f.get('email'), password: f.get('password') } }));
      await bootstrap();
    } catch (err) { toast(err.message, true); }
  };

  $('#form-signup').onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api('/auth/signup', { method: 'POST', auth: false, body: { email: f.get('email'), password: f.get('password'), full_name: f.get('full_name') || null } });
      tokens.set(await api('/auth/login', { method: 'POST', auth: false, form: { username: f.get('email'), password: f.get('password') } }));
      toast('Hoş geldin! 🎉');
      await bootstrap();
    } catch (err) { toast(err.message, true); }
  };

  $('#btn-logout').onclick = () => { tokens.clear(); state.user = null; showAuth(); toast('Çıkış yapıldı.'); };
  $('#btn-settings').onclick = () => switchTab('settings');

  async function bootstrap() {
    checkServerVersion();
    if (!tokens.access) { showAuth(); return; }
    try {
      state.user = await api('/auth/me');
      await showApp();
    } catch (_) { showAuth(); }
  }

  // ------------------------------------------------------------------------
  // Shared form helpers
  // ------------------------------------------------------------------------
  function fillCategorySelect(select, type) {
    const cats = type === 'income' ? INCOME_CATS : EXPENSE_CATS;
    select.innerHTML = cats.map((c) => `<option value="${c}">${CATEGORY_ICON[c]} ${CATEGORY_TR[c]}</option>`).join('');
  }
  function fillPaymentSelect(select, def = 'cash') {
    select.innerHTML = Object.entries(PAYMENT_TR).map(([k, v]) => `<option value="${k}" ${k === def ? 'selected' : ''}>${v}</option>`).join('');
  }
  function wireTypeSegment(form) {
    $$('.segment button[data-type]', form).forEach((btn) => {
      btn.onclick = () => {
        $$('.segment button[data-type]', form).forEach((b) => b.classList.remove('active', 'income', 'expense'));
        btn.classList.add('active', btn.dataset.type);
        form.type.value = btn.dataset.type;
        fillCategorySelect(form.category, btn.dataset.type);
      };
    });
  }
  function setTypeSegment(form, type) {
    $$('.segment button[data-type]', form).forEach((b) => { b.classList.remove('active', 'income', 'expense'); if (b.dataset.type === type) b.classList.add('active', type); });
    form.type.value = type;
    fillCategorySelect(form.category, type);
  }

  // ------------------------------------------------------------------------
  // BUGÜN
  // ------------------------------------------------------------------------
  const quickForm = $('#form-quick-add');
  fillCategorySelect(quickForm.category, 'expense');
  fillPaymentSelect(quickForm.payment_method, 'cash');
  wireTypeSegment(quickForm);

  quickForm.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(quickForm);
    const body = {
      type: f.get('type'), category: f.get('category'), amount: f.get('amount'),
      payment_method: f.get('payment_method'), description: f.get('description') || null,
      transaction_date: f.get('transaction_date') || null,
    };
    try {
      await api('/transactions', { method: 'POST', body });
      toast(body.type === 'income' ? 'Para eklendi ✅' : 'Harcama eklendi ✅');
      quickForm.amount.value = ''; quickForm.description.value = ''; quickForm.transaction_date.value = '';
      await loadToday();
    } catch (err) { toast(err.message, true); }
  };

  $('#btn-add-money').onclick = () => {
    setTypeSegment(quickForm, 'income');
    quickForm.category.value = 'salary';
    $('#quick-add-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
    quickForm.amount.focus();
  };

  function renderPlanSummary(plan) {
    state.plan = plan;
    state.periodType = plan.period_type;
    const [label, cls] = STATUS_TR[plan.status] || ['—', 'ok'];
    const badge = $('#plan-status-badge');
    badge.textContent = label; badge.className = `badge ${cls}`;
    $('#remaining-today').textContent = plan.status === 'no_income' ? '—' : money(Math.max(plan.remaining_today, 0));
    $('#today-sub').textContent = `Bugünkü limit ${money(plan.today_allowance)} · harcanan ${money(plan.spent_today)}`;
    const used = Number(plan.spent_today) + Number(plan.schedule.find((s) => s.is_today)?.reserved || 0);
    const ratio = Number(plan.today_allowance) > 0 ? Math.min(used / Number(plan.today_allowance), 1) : (used > 0 ? 1 : 0);
    const bar = $('#today-progress');
    bar.style.width = `${Math.round(ratio * 100)}%`;
    bar.parentElement.className = `progress ${ratio >= 1 ? 'over' : ratio >= 0.8 ? 'warn' : 'neutral'}`;
    $('#plan-status-msg').textContent = plan.status_message;
    $('#remaining-total').textContent = money(plan.remaining_total);
    $('#days-remaining').textContent = `${plan.days_remaining} gün`;
    $('#base-daily').textContent = money(plan.base_daily_allowance);
  }

  function renderWallet(w) {
    const bal = $('#wallet-balance');
    bal.textContent = money(w.balance_total);
    bal.classList.toggle('negative', Number(w.balance_total) < 0);
    $('#wallet-period-label').textContent = `Toplam bakiye · ${w.period_type === 'weekly' ? 'Bu hafta' : 'Bu ay'}: ${w.period_label}`;
    $('#wallet-period-remaining').textContent = money(w.period_remaining);
    $('#wallet-reserved').textContent = money(w.reserved_upcoming);
    $('#wallet-free').textContent = money(w.free_remaining);
    const list = $('#today-deductions');
    if (!w.today_deductions.length) {
      list.innerHTML = `<div class="muted small">Bugün için bekleyen otomatik düşüm yok${Number(w.auto_posted_today) > 0 ? ` · bugün düşülen: ${money(w.auto_posted_today)}` : ''}.</div>`;
    } else {
      list.innerHTML = w.today_deductions.map((u) => `
        <div class="item">
          <div class="icon">${CATEGORY_ICON[u.category] || '🔁'}</div>
          <div class="body"><div class="title">${escapeHtml(u.name)}</div><div class="sub">${fmtTime(u.scheduled_for)} · ${u.auto_post ? 'otomatik düşülecek' : 'hatırlatma'}</div></div>
          <div class="amount ${u.type}">${u.type === 'income' ? '+' : '−'}${money(u.amount)}</div>
          <button class="ghost" type="button" data-post-now="${u.rule_id}" title="Şimdi düş">✔️</button>
        </div>`).join('');
    }
  }

  $('#today-deductions').onclick = async (e) => {
    const id = e.target.closest('[data-post-now]')?.dataset.postNow;
    if (!id) return;
    try { await api(`/recurring/${id}/post-now`, { method: 'POST' }); toast('Düşüldü ✅'); await loadToday(); }
    catch (err) { toast(err.message, true); }
  };

  function txItem(t, { deletable = false } = {}) {
    const cls = t.type === 'income' ? 'income' : 'expense';
    const sign = t.type === 'income' ? '+' : '−';
    const auto = t.source === 'recurring' ? ' <span class="badge ok" title="Otomatik düşüldü">🔁</span>' : '';
    return `
      <div class="item" data-id="${t.id}">
        <div class="icon">${CATEGORY_ICON[t.category] || '•'}</div>
        <div class="body">
          <div class="title">${CATEGORY_TR[t.category] || t.category}${t.description ? ` · <span class="muted">${escapeHtml(t.description)}</span>` : ''}${auto}</div>
          <div class="sub">${fmtDateTime(t.transaction_date)} · ${PAYMENT_TR[t.payment_method] || t.payment_method}</div>
        </div>
        <div class="amount ${cls}">${sign}${money(t.amount)}</div>
        ${deletable ? `<button class="ghost" type="button" data-del="${t.id}" aria-label="Sil">🗑️</button>` : ''}
      </div>`;
  }

  async function loadToday() {
    try {
      const [msg, plan, wallet, recent] = await Promise.all([
        api('/motivation/today'), api('/planning/daily'), api('/wallet'), api('/transactions?page_size=5'),
      ]);
      $('#mot-title').textContent = msg.title;
      $('#mot-body').textContent = msg.body;
      $('#mot-quote').textContent = `“${msg.quote}”`;
      renderPlanSummary(plan);
      renderWallet(wallet);
      $('#recent-list').innerHTML = recent.items.length
        ? recent.items.map((t) => txItem(t)).join('')
        : '<div class="empty">Henüz işlem yok. "+ Para ekle" ile başla, sonra harcamalarını gir 👆</div>';
    } catch (err) { toast(err.message, true); }
  }

  // ------------------------------------------------------------------------
  // PLAN
  // ------------------------------------------------------------------------
  const planForm = $('#form-plan');
  function setPeriodTypeUI(ptype) {
    planForm.period_type.value = ptype;
    $$('#ptype-segment button').forEach((b) => b.classList.toggle('active', b.dataset.ptype === ptype));
    $('#income-label').textContent = ptype === 'weekly' ? 'Haftalık gelir (₺)' : 'Aylık gelir / maaş (₺)';
    $('#savings-label').textContent = ptype === 'weekly' ? 'Bu hafta kenara koymak istediğin birikim (₺)' : 'Bu ay kenara koymak istediğin birikim (₺)';
    planForm.income_override.placeholder = ptype === 'weekly' ? 'Örn. 3500' : 'Örn. 30000';
  }
  $$('#ptype-segment button').forEach((b) => { b.onclick = () => setPeriodTypeUI(b.dataset.ptype); });

  planForm.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(planForm);
    try {
      await api('/planning', {
        method: 'PUT',
        body: {
          period_type: f.get('period_type'),
          period: isoDate(new Date()),
          savings_goal: f.get('savings_goal') || '0',
          income_override: f.get('income_override') || null,
        },
      });
      toast('Plan kaydedildi ✅');
      await loadPlan();
    } catch (err) { toast(err.message, true); }
  };

  const budgetForm = $('#form-budget');
  fillCategorySelect(budgetForm.category, 'expense');
  budgetForm.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(budgetForm);
    try {
      await api('/budgets', { method: 'POST', body: { category: f.get('category'), monthly_limit: f.get('monthly_limit'), period: isoDate(new Date()) } });
      toast('Bütçe eklendi ✅');
      budgetForm.monthly_limit.value = '';
      await loadBudgets();
    } catch (err) { toast(err.message, true); }
  };

  async function loadBudgets() {
    try {
      const [statuses, budgets] = await Promise.all([api('/budgets/status'), api('/budgets')]);
      const byCat = Object.fromEntries(budgets.map((b) => [b.category, b]));
      $('#budget-list').innerHTML = statuses.length ? statuses.map((s) => {
        const pct = Math.min(Number(s.utilization_percent), 100);
        const cls = s.is_exceeded ? 'over' : s.is_over_threshold ? 'warn' : 'neutral';
        return `
          <div class="item" style="flex-wrap:wrap">
            <div class="icon">${CATEGORY_ICON[s.category]}</div>
            <div class="body">
              <div class="title">${CATEGORY_TR[s.category]} <span class="muted small">%${Number(s.utilization_percent).toFixed(0)}</span></div>
              <div class="sub">${money(s.spent)} / ${money(s.monthly_limit)} · kalan ${money(s.remaining)}</div>
            </div>
            <button class="ghost" type="button" data-del-budget="${byCat[s.category]?.id}" aria-label="Sil">🗑️</button>
            <div class="progress ${cls}" style="flex-basis:100%;margin-top:6px"><span style="width:${pct}%"></span></div>
          </div>`;
      }).join('') : '<div class="empty">Kategori bütçesi yok. Aşağıdan ekleyebilirsin.</div>';
    } catch (err) { toast(err.message, true); }
  }

  $('#budget-list').onclick = async (e) => {
    const id = e.target.closest('[data-del-budget]')?.dataset.delBudget;
    if (!id || !confirm('Bu bütçe silinsin mi?')) return;
    try { await api(`/budgets/${id}`, { method: 'DELETE' }); toast('Bütçe silindi.'); await loadBudgets(); }
    catch (err) { toast(err.message, true); }
  };

  async function loadPlan() {
    try {
      const plan = await api('/planning/daily');
      const settings = await api(`/planning?period_type=${plan.period_type}`).catch(() => null);
      renderPlanSummary(plan);
      setPeriodTypeUI(plan.period_type);
      planForm.income_override.value = settings?.income_override ?? '';
      planForm.savings_goal.value = settings?.savings_goal ?? '0';

      $('#plan-period-label').textContent = plan.period_label;
      $('#p-income').textContent = money(plan.income_basis) + (plan.income_is_override ? '' : ' (girilen)');
      $('#p-savings').textContent = money(plan.savings_goal);
      $('#p-spendable').textContent = money(plan.spendable_total);
      $('#p-reserved').textContent = money(plan.reserved_total);
      $('#p-spent').textContent = money(plan.spent_so_far);
      $('#p-free').textContent = money(plan.free_remaining);

      $('#schedule-table tbody').innerHTML = plan.schedule.map((s) => {
        const d = new Date(s.day);
        const cls = s.is_today ? 'today' : (!s.is_past ? 'future' : '');
        const diffCls = s.difference === null ? '' : (Number(s.difference) >= 0 ? 'pos' : 'neg');
        return `<tr class="${cls}">
          <td>${pad(d.getDate())} ${s.weekday}${s.is_today ? ' · bugün' : ''}</td>
          <td>${money(s.planned)}</td>
          <td>${Number(s.reserved) > 0 ? money(s.reserved) : '—'}</td>
          <td>${s.spent === null ? '—' : money(s.spent)}</td>
          <td class="${diffCls}">${s.difference === null ? '—' : (Number(s.difference) >= 0 ? '+' : '') + money(s.difference)}</td>
        </tr>`;
      }).join('');

      drawChart('plan', $('#chart-plan'), {
        type: 'bar',
        data: {
          labels: plan.chart.labels,
          datasets: [
            { type: 'line', label: 'Planlanan', data: plan.chart.datasets[0].data.map(Number), borderColor: cssVar('--accent'), backgroundColor: cssVar('--accent'), pointRadius: 0, borderWidth: 2, tension: .2 },
            { label: 'Harcanan', data: plan.chart.datasets[1].data.map((v) => v === null ? null : Number(v)), backgroundColor: plan.schedule.map((s) => s.is_today ? cssVar('--warn') : cssVar('--danger')), borderRadius: 4 },
          ],
        },
        options: baseChartOptions({ yMoney: true }),
      });
      await loadBudgets();
    } catch (err) { toast(err.message, true); }
  }

  // ------------------------------------------------------------------------
  // SABİT / TEKRARLAYAN
  // ------------------------------------------------------------------------
  const ruleForm = $('#form-rule');
  fillCategorySelect(ruleForm.category, 'expense');
  fillPaymentSelect(ruleForm.payment_method, 'cash');
  wireTypeSegment(ruleForm);
  ruleForm.start_date.value = isoDate(new Date());
  ruleForm.frequency.onchange = () => {
    $('#weekday-field').hidden = ruleForm.frequency.value !== 'weekly';
    $('#dom-field').hidden = ruleForm.frequency.value !== 'monthly';
  };

  function describeRule(r) {
    const t = String(r.time_of_day).slice(0, 5);
    if (r.frequency === 'daily') return `Her gün ${t}`;
    if (r.frequency === 'weekly') return `${r.weekdays.map((d) => WEEKDAYS_TR[d]).join(', ')} ${t}`;
    return `Her ayın ${r.day_of_month}. günü ${t}`;
  }

  ruleForm.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(ruleForm);
    const body = {
      name: f.get('name'), type: f.get('type'), category: f.get('category'), amount: f.get('amount'),
      payment_method: f.get('payment_method'), frequency: f.get('frequency'),
      weekdays: f.getAll('weekdays').map(Number), day_of_month: f.get('frequency') === 'monthly' ? Number(f.get('day_of_month')) : null,
      time_of_day: f.get('time_of_day'), start_date: f.get('start_date'), end_date: f.get('end_date') || null,
      auto_post: ruleForm.auto_post.checked,
    };
    try {
      await api('/recurring', { method: 'POST', body });
      toast('Sabit işlem kaydedildi ✅');
      ruleForm.name.value = ''; ruleForm.amount.value = '';
      await loadRecurring();
    } catch (err) { toast(err.message, true); }
  };

  async function loadRecurring() {
    try {
      const [rules, upcoming] = await Promise.all([api('/recurring'), api('/recurring/upcoming?days=7')]);
      $('#rule-list').innerHTML = rules.length ? rules.map((r) => `
        <div class="item ${r.is_active ? '' : 'inactive'}" style="flex-wrap:wrap">
          <div class="icon">${CATEGORY_ICON[r.category] || '🔁'}</div>
          <div class="body">
            <div class="title">${escapeHtml(r.name)} <span class="muted small">· ${CATEGORY_TR[r.category]}</span></div>
            <div class="sub">${describeRule(r)} · ${r.auto_post ? 'otomatik' : 'hatırlatma'}${r.next_run_at ? ` · sıradaki: ${fmtDateTime(r.next_run_at)}` : ''}</div>
          </div>
          <div class="amount ${r.type}">${r.type === 'income' ? '+' : '−'}${money(r.amount)}</div>
          <div class="row" style="flex-basis:100%;justify-content:flex-end;gap:4px;margin-top:4px">
            <label class="switch small"><input type="checkbox" data-toggle="${r.id}" ${r.is_active ? 'checked' : ''}> ${r.is_active ? 'Aktif' : 'Pasif'}</label>
            <button class="ghost" type="button" data-post-now="${r.id}">Şimdi düş</button>
            <button class="ghost" type="button" data-del-rule="${r.id}" aria-label="Sil">🗑️</button>
          </div>
        </div>`).join('') : '<div class="empty">Henüz sabit işlem yok. Aşağıdan ekle: örn. Öğle yemeği · 150 ₺ · her gün 12:30.</div>';

      $('#upcoming-list').innerHTML = upcoming.length ? upcoming.map((u) => `
        <div class="item">
          <div class="icon">${CATEGORY_ICON[u.category] || '🔁'}</div>
          <div class="body"><div class="title">${escapeHtml(u.name)}</div><div class="sub">${fmtDayShort(u.scheduled_for)} · ${fmtTime(u.scheduled_for)}${u.is_today ? ' · bugün' : ''}</div></div>
          <div class="amount ${u.type}">${u.type === 'income' ? '+' : '−'}${money(u.amount)}</div>
        </div>`).join('') : '<div class="empty">Önümüzdeki 7 günde planlı işlem yok.</div>';
    } catch (err) { toast(err.message, true); }
  }

  $('#rule-list').onclick = async (e) => {
    const del = e.target.closest('[data-del-rule]')?.dataset.delRule;
    const post = e.target.closest('[data-post-now]')?.dataset.postNow;
    try {
      if (del) {
        if (!confirm('Bu sabit işlem silinsin mi? (Geçmiş kayıtlar silinmez)')) return;
        await api(`/recurring/${del}`, { method: 'DELETE' }); toast('Silindi.'); await loadRecurring();
      } else if (post) {
        await api(`/recurring/${post}/post-now`, { method: 'POST' }); toast('Düşüldü ✅'); await loadRecurring();
      }
    } catch (err) { toast(err.message, true); }
  };
  $('#rule-list').onchange = async (e) => {
    const id = e.target.dataset.toggle;
    if (!id) return;
    try { await api(`/recurring/${id}`, { method: 'PATCH', body: { is_active: e.target.checked } }); await loadRecurring(); }
    catch (err) { toast(err.message, true); }
  };

  // ------------------------------------------------------------------------
  // İŞLEMLER
  // ------------------------------------------------------------------------
  $$('#tx-filter button').forEach((b) => {
    b.onclick = () => {
      $$('#tx-filter button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.txFilter = b.dataset.filter;
      loadTransactions(true);
    };
  });
  $('#tx-more').onclick = () => loadTransactions(false);

  async function loadTransactions(reset) {
    if (reset) { state.txPage = 1; $('#tx-list').innerHTML = ''; }
    try {
      const q = new URLSearchParams({ page: state.txPage, page_size: 20 });
      if (state.txFilter) q.set('type', state.txFilter);
      const data = await api(`/transactions?${q}`);
      state.txTotalPages = data.total_pages;
      const html = data.items.map((t) => txItem(t, { deletable: true })).join('');
      if (reset && !data.items.length) $('#tx-list').innerHTML = '<div class="empty">İşlem bulunamadı.</div>';
      else $('#tx-list').insertAdjacentHTML('beforeend', html);
      $('#tx-more').classList.toggle('hidden', state.txPage >= state.txTotalPages);
      state.txPage += 1;
    } catch (err) { toast(err.message, true); }
  }

  $('#tx-list').onclick = async (e) => {
    const id = e.target.closest('[data-del]')?.dataset.del;
    if (!id || !confirm('Bu işlem silinsin mi?')) return;
    try { await api(`/transactions/${id}`, { method: 'DELETE' }); toast('İşlem silindi.'); await loadTransactions(true); }
    catch (err) { toast(err.message, true); }
  };

  // ------------------------------------------------------------------------
  // ANALİZ
  // ------------------------------------------------------------------------
  $('#an-prev').onclick = () => { state.analyticsMonth.setMonth(state.analyticsMonth.getMonth() - 1); loadAnalytics(); };
  $('#an-next').onclick = () => { state.analyticsMonth.setMonth(state.analyticsMonth.getMonth() + 1); loadAnalytics(); };

  const PALETTE = ['#16a34a', '#2563eb', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569', '#0d9488', '#9333ea', '#ca8a04', '#be123c', '#1d4ed8'];

  async function loadAnalytics() {
    const period = isoDate(new Date(state.analyticsMonth.getFullYear(), state.analyticsMonth.getMonth(), 1));
    $('#an-month').textContent = monthLabel(state.analyticsMonth);
    try {
      const [summary, trend] = await Promise.all([api(`/analytics/summary?period=${period}`), api('/analytics/trend?months=6')]);
      $('#an-income').textContent = money(summary.total_income);
      $('#an-expense').textContent = money(summary.total_expense);
      $('#an-net').textContent = money(summary.net_savings);
      $('#an-rate').textContent = `%${Number(summary.savings_rate).toFixed(1)}`;
      const parts = [];
      if (summary.expense_change_percent !== null) parts.push(`Gider geçen aya göre ${Number(summary.expense_change_percent) >= 0 ? '↑' : '↓'} %${Math.abs(Number(summary.expense_change_percent)).toFixed(1)}`);
      if (summary.income_change_percent !== null) parts.push(`gelir ${Number(summary.income_change_percent) >= 0 ? '↑' : '↓'} %${Math.abs(Number(summary.income_change_percent)).toFixed(1)}`);
      $('#an-compare').textContent = parts.length ? parts.join(' · ') : `${summary.transaction_count} işlem`;

      const expenses = summary.category_breakdown.filter((c) => c.type === 'expense');
      drawChart('cat', $('#chart-cat'), {
        type: 'doughnut',
        data: {
          labels: expenses.map((c) => CATEGORY_TR[c.category]),
          datasets: [{ data: expenses.map((c) => Number(c.amount)), backgroundColor: expenses.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0 }],
        },
        options: { ...baseChartOptions({}), cutout: '62%', plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${money(ctx.parsed)}` } } } },
      });
      $('#cat-list').innerHTML = expenses.length ? expenses.map((c, i) => `
        <div class="item">
          <div class="icon" style="background:${PALETTE[i % PALETTE.length]}22">${CATEGORY_ICON[c.category]}</div>
          <div class="body"><div class="title">${CATEGORY_TR[c.category]}</div><div class="sub">%${Number(c.percentage).toFixed(1)}</div></div>
          <div class="amount">${money(c.amount)}</div>
        </div>`).join('') : '<div class="empty">Bu ay gider yok.</div>';

      drawChart('trend', $('#chart-trend'), {
        type: 'bar',
        data: {
          labels: trend.labels,
          datasets: [
            { label: 'Gelir', data: trend.datasets[0].data.map(Number), backgroundColor: cssVar('--accent'), borderRadius: 6 },
            { label: 'Gider', data: trend.datasets[1].data.map(Number), backgroundColor: cssVar('--danger'), borderRadius: 6 },
            { type: 'line', label: 'Net', data: trend.datasets[2].data.map(Number), borderColor: cssVar('--info'), backgroundColor: cssVar('--info'), tension: .3, pointRadius: 3 },
          ],
        },
        options: baseChartOptions({ yMoney: true }),
      });
    } catch (err) { toast(err.message, true); }
  }

  // ------------------------------------------------------------------------
  // AYARLAR / Bildirim / Kurulum / Yedek
  // ------------------------------------------------------------------------
  function urlBase64ToUint8Array(base64) {
    const padding = '='.repeat((4 - (base64.length % 4)) % 4);
    const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  async function getSwRegistration() {
    if (!('serviceWorker' in navigator)) return null;
    return navigator.serviceWorker.getRegistration() || navigator.serviceWorker.ready;
  }

  async function notificationStatus() {
    if (!window.isSecureContext) return ['Güvenli bağlantı gerekli (HTTPS veya localhost).', 'err'];
    if (!('Notification' in window) || !('PushManager' in window)) return ['Bu tarayıcı bildirim desteklemiyor.', 'err'];
    if (Notification.permission === 'denied') return ['Bildirim izni reddedilmiş. Tarayıcı site ayarlarından izin ver.', 'err'];
    const reg = await getSwRegistration();
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (sub) return ['Bu cihazda bildirimler açık ✅', 'ok'];
    return ['Bildirimler bu cihazda kapalı.', 'warn'];
  }

  async function loadSettings() {
    const [text, cls] = await notificationStatus();
    $('#notif-status').innerHTML = `<span class="badge ${cls}">${text}</span>`;
    $('#notif-insecure').classList.toggle('hidden', window.isSecureContext);
    $('#btn-install').classList.toggle('hidden', !state.installPrompt);
    try {
      const [alerts, backups] = await Promise.all([api('/alerts'), api('/system/backups').catch(() => [])]);
      $('#backup-info').textContent = backups.length ? `Son yedek: ${fmtDateTime(backups[0].created_at)} (${backups.length} dosya)` : 'Henüz yedek yok.';
      $('#alert-list').innerHTML = alerts.length ? alerts.map((a) => `
        <div class="item">
          <div class="icon">${a.is_read ? '✅' : '⚠️'}</div>
          <div class="body"><div class="title">${CATEGORY_TR[a.category]} · %${Number(a.utilization_percent).toFixed(0)}</div><div class="sub">${escapeHtml(a.message)}</div></div>
          ${a.is_read ? '' : `<button class="ghost" type="button" data-read="${a.id}">Okudum</button>`}
        </div>`).join('') : '<div class="empty">Uyarı yok — bütçeler yolunda 👍</div>';
    } catch (err) { toast(err.message, true); }
  }

  $('#alert-list').onclick = async (e) => {
    const id = e.target.closest('[data-read]')?.dataset.read;
    if (!id) return;
    try { await api(`/alerts/${id}/read`, { method: 'PATCH' }); await loadSettings(); } catch (err) { toast(err.message, true); }
  };

  $('#btn-backup').onclick = async () => {
    try {
      const r = await api('/system/backup', { method: 'POST' });
      toast(`Yedek alındı ✅ (${Math.round(r.size_bytes / 1024)} KB)`);
      await loadSettings();
    } catch (err) { toast(err.message, true); }
  };

  $('#btn-notif-enable').onclick = async () => {
    try {
      if (!window.isSecureContext) throw new Error('Bildirim için HTTPS (veya PC\'de localhost) gerekir. Rehberdeki adımları izle.');
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') throw new Error('Bildirim izni verilmedi.');
      const reg = await getSwRegistration();
      if (!reg) throw new Error('Service worker hazır değil, sayfayı yenile.');
      const { public_key } = await api('/push/vapid-public-key', { auth: false });
      let sub = await reg.pushManager.getSubscription();
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(public_key) });
      await api('/push/subscribe', { method: 'POST', body: sub.toJSON() });
      toast('Bildirimler açıldı ✅');
      await loadSettings();
    } catch (err) { toast(err.message, true); }
  };

  $('#btn-notif-test').onclick = async () => {
    try {
      const r = await api('/push/test', { method: 'POST' });
      toast(r.sent ? `Test gönderildi (${r.sent} cihaz) 📲` : 'Kayıtlı cihaz yok — önce "Bildirimleri Aç".', !r.sent);
    } catch (err) { toast(err.message, true); }
  };

  $('#btn-notif-today').onclick = async () => {
    try {
      const r = await api('/motivation/send-now', { method: 'POST' });
      toast(r.sent ? `Bugünün mesajı gönderildi (${r.sent} cihaz) ☀️` : 'Kayıtlı cihaz yok — önce "Bildirimleri Aç".', !r.sent);
    } catch (err) { toast(err.message, true); }
  };

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    state.installPrompt = e;
    $('#btn-install').classList.remove('hidden');
  });
  $('#btn-install').onclick = async () => {
    if (!state.installPrompt) return;
    state.installPrompt.prompt();
    const { outcome } = await state.installPrompt.userChoice;
    if (outcome === 'accepted') toast('Uygulama kuruldu 🎉');
    state.installPrompt = null;
    $('#btn-install').classList.add('hidden');
  };

  // ------------------------------------------------------------------------
  // Charts
  // ------------------------------------------------------------------------
  function baseChartOptions({ yMoney = false } = {}) {
    const grid = cssVar('--border');
    const text = cssVar('--muted');
    return {
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      plugins: {
        legend: { labels: { color: text, boxWidth: 12, usePointStyle: true } },
        tooltip: { callbacks: yMoney ? { label: (ctx) => ` ${ctx.dataset.label}: ${money(ctx.parsed.y)}` } : {} },
      },
      scales: yMoney ? {
        x: { grid: { display: false }, ticks: { color: text, maxRotation: 0, autoSkip: true } },
        y: { grid: { color: grid }, ticks: { color: text, callback: (v) => money(v).replace(',00', '') }, beginAtZero: true },
      } : {},
    };
  }

  function drawChart(key, canvas, config) {
    if (typeof Chart === 'undefined') { canvas.replaceWith(Object.assign(document.createElement('div'), { className: 'empty', textContent: 'Grafik kütüphanesi yüklenemedi (çevrimdışı?).' })); return; }
    state.charts[key]?.destroy();
    state.charts[key] = new Chart(canvas, config);
  }

  // ------------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------------
  $$('nav.tabbar button').forEach((b) => { b.onclick = () => switchTab(b.dataset.tab); });
  $$('[data-goto]').forEach((b) => { b.onclick = () => switchTab(b.dataset.goto); });
  window.addEventListener('hashchange', () => {
    const t = location.hash.slice(1);
    if (state.user && TABS.includes(t)) switchTab(t);
  });
  // Refresh the wallet when the tab regains focus (e.g. after a push notification).
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.user && (location.hash || '#today') === '#today') loadToday();
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch((e) => console.warn('SW kaydı başarısız', e)));
  }

  bootstrap();
})();
