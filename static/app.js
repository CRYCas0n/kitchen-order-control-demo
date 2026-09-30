'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => value ? value.slice(0,10).split('-').reverse().join('.') : '—';
const rub = value => value === null || value === undefined ? 'Нет данных' : new Intl.NumberFormat('ru-RU', {maximumFractionDigits:2}).format(value) + ' ₽';
const time = value => new Date(value).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const labels = {active:'Активные заказы',overdue:'Просроченные',open_problem:'С открытыми проблемами',delay_risk:'С риском задержки',incomplete:'Неполные финансовые данные',low_margin:'Низкая / отрицательная маржинальность'};
const costLabels = {revenue:'Выручка с учётом скидок',materials:'Материалы',manufacturing:'Изготовление',delivery:'Доставка',installation:'Монтаж',commission:'Комиссия',rework:'Переделки и рекламации'};
let snapshot = null, lastSuccess = null, kpiFilter = '', selectedOrder = null, requestNumber = 0;

function tags(order) {
  if (order.data_error) return `<span class="badge red">${esc(order.data_error)}</span>`;
  let result = '';
  if (order.overdue) result += '<span class="badge red">Просрочен</span>';
  if (order.delay_risk) result += '<span class="badge orange">Риск задержки</span>';
  if (!order.active) result += `<span class="badge ${order.completed_late?'orange':'green'}">${esc(order.deadline_label)}</span>`;
  if (order.open_problem) result += `<span class="badge red">${esc(order.problem_type || 'Открытая проблема')}</span>`;
  if (order.incomplete) result += '<span class="badge gray">Фактические данные неполные</span>';
  if (order.low_margin) result += `<span class="badge ${order.economy.actual.negative_margin?'red':'orange'}">${order.economy.actual.negative_margin?'Отрицательный доход':'Низкая маржинальность'}</span>`;
  return result;
}

function filtered() {
  return snapshot.orders.filter(o => (!kpiFilter || o[kpiFilter]) &&
    ['stage','sales_point','stage_executor'].every(key => !$(key).value || o[key] === $(key).value) &&
    (!$('problem').value || Boolean(o.open_problem) === ($('problem').value === 'yes')));
}

function populateFilters() {
  for (const key of ['stage','sales_point','stage_executor']) {
    const select = $(key), old = select.value, first = select.options[0].outerHTML;
    const values = key === 'stage' ? snapshot.stages : [...new Set(snapshot.orders.map(o => o[key]))].sort();
    select.innerHTML = first + values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
    if (values.includes(old)) select.value = old;
  }
}

function chartRows(rows, total) {
  return rows.map(([key,label,count,tone])=>`<div class="chart-row tone-${tone}" data-bucket="${key}" data-count="${count}"><span class="chart-label">${esc(label)}</span><progress max="${Math.max(1,total)}" value="${count}" aria-hidden="true"></progress><strong class="chart-count">${count}</strong></div>`).join('');
}

function renderOverview() {
  const summary = snapshot.summary, finance = summary.finance;
  $('overview-count').textContent = `Все ${summary.total_count} заказов`;
  $('kpis').innerHTML = Object.entries(labels).map(([key,label])=>`<button class="kpi ${kpiFilter===key?'active':''}" data-filter="${key}" aria-pressed="${kpiFilter===key}"><span class="kpi-label">${label}</span><span class="kpi-value">${summary.kpis[key]}</span><span class="kpi-foot">${key==='active'?'До закрытия заказа':key==='overdue'?'Активные, срок истёк':key==='delay_risk'?'Прогноз позже обещанного':key==='low_margin'?`Порог ${snapshot.low_margin_threshold}%`:'Проверить на планёрке'} ↗</span></button>`).join('');
  $('stage-chart').innerHTML = summary.stages.map(row=>`<div class="stage-row" data-stage="${esc(row.stage)}" data-count="${row.count}"><span>${esc(row.stage)}</span><progress value="${row.count}" max="${Math.max(1,...summary.stages.map(s=>s.count))}" aria-hidden="true"></progress><strong>${row.count}</strong></div>`).join('');
  const deadlines = summary.deadlines;
  $('deadline-chart').innerHTML = chartRows([
    ['on_time','В срок',deadlines.on_time,'green'],['risk','Риск задержки',deadlines.risk,'orange'],
    ['overdue','Просрочено',deadlines.overdue,'red'],['completed_late','Завершено с опозданием',deadlines.completed_late,'red'],
  ], summary.total_count);
  $('finance-metrics').innerHTML = [
    ['revenue_actual','Фактическая выручка',rub(finance.revenue_actual),''],
    ['margin_income','Маржинальный доход',rub(finance.margin_income),finance.margin_income<0?'negative':''],
    ['average_margin_percent','Средняя маржинальность',finance.average_margin_percent===null?'Не рассчитывается':new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}).format(finance.average_margin_percent)+'%',''],
    ['loss_count','Убыточные заказы',finance.loss_count,finance.loss_count?'negative':''],
  ].map(([key,label,value,tone])=>`<div><dt>${label}</dt><dd data-metric="${key}" class="${tone}">${value}</dd></div>`).join('');
  $('finance-note').textContent = `Суммы: ${finance.complete_count} из ${summary.total_count} заказов с полным фактом. Среднее арифметическое: ${finance.average_count} заказов с рассчитанным процентом.`;
  $('margin-threshold').textContent = snapshot.low_margin_threshold;
  const margins = summary.margins;
  const marginRows = [['normal','Нормальная',margins.normal,'green'],['low','Низкая',margins.low,'orange'],
    ['negative','Отрицательная',margins.negative,'red'],['incomplete','Данные неполные',margins.incomplete,'gray']];
  if(margins.not_calculable) marginRows.push(['not_calculable','Не рассчитывается: выручка 0',margins.not_calculable,'gray']);
  $('margin-chart').innerHTML = chartRows(marginRows, summary.total_count);
  $('summary-error').hidden = !summary.invalid_count;
  $('summary-error').textContent = `Ошибка данных у ${summary.invalid_count} заказов. Они исключены из экономики и диаграммы сроков и отмечены в карточках.`;
  const attention = summary.attention_ids.map(id=>snapshot.orders.find(o=>o.id===id)).filter(Boolean);
  $('attention-count').textContent = `${attention.length} из ${summary.attention_total}`;
  $('attention').innerHTML = attention.length ? attention.map(o=>`<tr><td><button class="order-link" data-order="${o.id}">${esc(o.order_number)} ↗</button></td><td>${tags(o)}${o.open_problem?`<span class="attention-comment" title="${esc(o.problem_comment)}">${esc(o.problem_comment)}</span>`:''}</td><td>${esc(o.stage)}</td><td>${esc(o.stage_executor)}</td><td>${date(o.next_action_due)}</td></tr>`).join('') : '<tr><td colspan="5">Нет заказов, требующих внимания.</td></tr>';
}

function validSnapshot(data) {
  const s=data?.summary;
  const counts=values=>values.every(value=>Number.isInteger(value)&&value>=0);
  return Array.isArray(data?.orders) && Array.isArray(data.stages) && Boolean(data.demo_date) &&
    s?.total_count===data.orders.length && Array.isArray(s.stages) && s.stages.every(row=>typeof row.stage==='string'&&counts([row.count])) &&
    s.kpis && counts(Object.keys(labels).map(key=>s.kpis[key])) &&
    s.deadlines && counts(['on_time','risk','overdue','completed_late'].map(key=>s.deadlines[key])) &&
    s.margins && counts(['normal','low','negative','incomplete','not_calculable'].map(key=>s.margins[key])) &&
    s.finance && ['revenue_actual','margin_income','average_margin_percent'].every(key=>s.finance[key]===null||Number.isFinite(s.finance[key])) &&
    counts([s.finance.complete_count,s.finance.average_count,s.finance.loss_count,s.attention_total,s.invalid_count]) &&
    Array.isArray(s.attention_ids) && s.attention_ids.every(id=>data.orders.some(o=>o.id===id));
}

function render() {
  if (!snapshot) return;
  $('demo-date').textContent = date(snapshot.demo_date);
  $('threshold').textContent = snapshot.low_margin_threshold;
  $('data-source').textContent = $('mode').value === 'simulation' ? 'Источник: локальный учебный пример' : 'Источник: backend · SQLite';
  renderOverview();
  const orders = filtered();
  $('order-count').textContent = `${orders.length} из ${snapshot.orders.length}`;
  $('active-filter').textContent = kpiFilter ? `Фильтр: ${labels[kpiFilter]}` : 'Все показатели';
  $('empty').hidden = orders.length > 0;
  const visibleStages = $('stage').value ? [$('stage').value] : snapshot.stages;
  $('board').innerHTML = visibleStages.map(stage=>{
    const group = orders.filter(o=>o.stage===stage);
    return `<div class="column"><div class="column-header">${esc(stage)}<span>${group.length}</span></div>${group.map(o=>`<button class="order-card" data-order="${o.id}"><div class="card-top"><span class="card-number">${esc(o.order_number)}</span><span class="card-client">${esc(o.client_alias)}</span></div><div class="card-point">${esc(o.sales_point_type)} · ${esc(o.sales_point)}</div><div class="card-dates"><span>Обещано клиенту</span><strong class="${o.overdue?'late':''}">${date(o.promised_date_initial)}</strong><span>Текущий прогноз</span><strong>${date(o.forecast_date)}</strong></div><div class="card-action">↳ ${esc(o.next_action)}</div><div class="card-executor">${esc(o.stage_executor)}</div><div class="card-badges">${tags(o)}</div></button>`).join('') || '<p class="column-empty">Нет заказов</p>'}</div>`;
  }).join('');
  if (selectedOrder !== null && $('details').open) showOrder(selectedOrder);
}

function showOrder(id) {
  const order = snapshot?.orders.find(o=>o.id===id);
  if (!order) return;
  selectedOrder = id;
  const fields = {client_alias:'Условный клиент',sales_point:'Точка продаж',city:'Город',coordinator:'Координатор',stage_executor:'Исполнитель этапа',stage:'Стадия',promised_date_initial:'Первоначально обещано',forecast_date:'Текущий прогноз',completed_date:'Фактическое завершение',next_action:'Следующее действие',next_action_due:'Срок следующего действия',project_version:'Согласованная версия проекта'};
  let economy = '';
  if (!order.data_error) {
    const p=order.economy.plan,a=order.economy.actual;
    economy = `<section class="detail-section" id="economy"><h3>Экономика заказа</h3><div class="table-wrap"><table class="economy-table"><thead><tr><th>Показатель</th><th>План</th><th>Факт</th></tr></thead><tbody>${Object.entries(costLabels).map(([key,label])=>`<tr><td>${label}</td><td>${rub(order.costs[key+'_plan'])}</td><td>${rub(order.costs[key+'_actual'])}</td></tr>`).join('')}<tr class="economy-total"><td>Переменные затраты</td><td>${rub(p.variable_costs)}</td><td>${rub(a.variable_costs)}</td></tr><tr class="economy-total"><td>Маржинальный доход</td><td>${rub(p.margin_income)}</td><td>${rub(a.margin_income)}</td></tr><tr><td>Маржинальность</td><td>${p.margin_percent===null?'Не рассчитывается':p.margin_percent.toFixed(2)+'%'}</td><td>${a.margin_percent===null?'Не рассчитывается':a.margin_percent.toFixed(2)+'%'}</td></tr></tbody></table></div><p class="economy-note">${a.complete?'Фактические данные полные.':'Фактические данные неполные. Отсутствуют: '+a.missing.map(k=>costLabels[k]).join(', ')+'.'} Нулевой расход подтверждён; «Нет данных» означает отсутствие значения. Маржинальный доход не является чистой прибылью. Постоянные расходы не распределены. Все суммы без НДС. Порог низкой маржинальности: ${snapshot.low_margin_threshold}%.</p></section>`;
  }
  $('detail-content').innerHTML = `<h2 id="detail-title" class="detail-heading">${esc(order.order_number)} <span class="badge green">${esc(order.stage)}</span></h2><div>${tags(order)}</div><dl class="detail-grid">${Object.entries(fields).map(([key,label])=>`<div><dt>${label}</dt><dd>${key.includes('date')||key==='next_action_due'?date(order[key]):esc(order[key])}</dd></div>`).join('')}</dl>${order.problem_type?`<div class="notice ${order.open_problem?'danger':'warning'}"><strong>${esc(order.problem_type)} · ${order.open_problem?'Открыта':'Решена'}</strong><p>${esc(order.problem_comment)}</p><p>Нужна помощь: ${esc(order.problem_help_needed)}</p></div>`:'<p class="economy-note">Открытых проблем нет.</p>'}${order.tasks?.length?`<section class="detail-section"><h3>Задания исполнителей</h3>${order.tasks.map(t=>`<p class="economy-note">${t.role==='installer'?'Монтаж':'Замер'} · ${{new:'Новое',accepted:'Принято',problem:'Проблема',transfer_requested:'Запрошен перенос',completed:'Выполнено'}[t.status] || esc(t.status)}${t.proposed_date?' · Предложен перенос: '+date(t.proposed_date)+' — '+esc(t.transfer_reason):''}</p>`).join('')}</section>`:''}${economy}<section class="detail-section"><h3>История обновлений</h3>${(order.history||[]).map(h=>`<article class="history-event"><span class="history-meta">${time(h.created_at)} · ${{telegram:'Telegram',admin:'Admin',simulation:'Имитация',system:'Система'}[h.source] || esc(h.source)} / ${esc(h.actor_ref)}</span><p>${esc(h.comment)}</p></article>`).join('')||'<p class="muted">Событий пока нет.</p>'}</section>`;
  if (!$('details').open) $('details').showModal();
}

async function refresh() {
  const request = ++requestNumber, mode = $('mode').value;
  $('refresh').disabled = true;
  try {
    const response = await fetch(mode==='simulation'?'/static/demo-data.json':'/api/dashboard', {cache:'no-store',signal:AbortSignal.timeout(12000)});
    if (!response.ok) throw new Error('HTTP '+response.status);
    const data = await response.json();
    if (!validSnapshot(data) || (mode==='backend' && data.source!=='backend')) throw new Error('Invalid response');
    if (request !== requestNumber) return;
    snapshot = data;
    lastSuccess = new Date().toISOString();
    $('last-updated').textContent = time(lastSuccess);
    $('error').hidden = true;
    populateFilters();
    render();
  } catch {
    if (request !== requestNumber) return;
    $('error').hidden = false;
    $('error').textContent = snapshot ? `Связь с сервером недоступна. Показаны данные от ${time(lastSuccess)}. Информация может быть устаревшей.` : 'Не удалось получить данные. Повторите запрос или явно выберите «Режим имитации».';
  } finally {
    if (request === requestNumber) $('refresh').disabled = false;
  }
}

$('refresh').addEventListener('click',refresh);
$('mode').addEventListener('change',()=>{
  snapshot = null; lastSuccess = null; selectedOrder = null;
  $('details').close(); $('last-updated').textContent='—'; $('kpis').replaceChildren(); $('board').replaceChildren(); $('attention').replaceChildren();
  for(const key of ['stage-chart','deadline-chart','finance-metrics','finance-note','margin-chart']) $(key).replaceChildren();
  $('summary-error').hidden=true; $('overview-count').textContent='Загрузка…'; $('attention-count').textContent='—';
  $('simulation-notice').hidden = $('mode').value !== 'simulation';
  $('data-source').textContent='Загрузка выбранного источника…';
  refresh();
});
for(const key of ['stage','sales_point','stage_executor','problem']) $(key).addEventListener('change',render);
$('reset').addEventListener('click',()=>{kpiFilter='';for(const key of ['stage','sales_point','stage_executor','problem']) $(key).value='';render();});
document.addEventListener('click',event=>{
  const kpi=event.target.closest('[data-filter]'); if(kpi){kpiFilter=kpiFilter===kpi.dataset.filter?'':kpi.dataset.filter;for(const key of ['stage','sales_point','stage_executor','problem']) $(key).value='';render();}
  const card=event.target.closest('[data-order]'); if(card)showOrder(Number(card.dataset.order));
});
$('close-details').addEventListener('click',()=>$('details').close());
$('details').addEventListener('click',event=>{if(event.target===$('details')){const r=$('details').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('details').close();}});
$('simulate').addEventListener('click',()=>{
  if($('mode').value!=='simulation'||!snapshot)return;
  const scenario=snapshot.simulation;
  if(!scenario)return;
  const order=snapshot.orders.find(o=>o.id===scenario.order_id);
  Object.assign(order,scenario.changes);
  snapshot.summary=scenario.summary;
  snapshot.kpis=scenario.summary.kpis;
  order.history.unshift({source:'simulation',actor_ref:'Учебный монтажник',created_at:new Date().toISOString(),comment:'Имитация сообщения: отсутствует фасад 600 мм. Telegram и рабочая база не использовались.'});
  render();showOrder(order.id);
});
refresh();
