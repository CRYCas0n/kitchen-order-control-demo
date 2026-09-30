'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => value ? value.slice(0,10).split('-').reverse().join('.') : '—';
const rub = value => value === null || value === undefined ? 'Нет данных' : new Intl.NumberFormat('ru-RU', {maximumFractionDigits:2}).format(value) + ' ₽';
const time = value => new Date(value).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const labels = {active:'Активные заказы',overdue:'Просроченные активные',open_problem:'С открытыми проблемами',incomplete:'Неполные финансовые данные',low_margin:'Низкая / отрицательная маржа'};
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

function render() {
  if (!snapshot) return;
  $('demo-date').textContent = date(snapshot.demo_date);
  $('threshold').textContent = snapshot.low_margin_threshold;
  $('data-source').textContent = $('mode').value === 'simulation' ? 'Источник: локальный учебный пример' : 'Источник: backend · SQLite';
  $('kpis').innerHTML = Object.entries(labels).map(([key,label])=>`<button class="kpi ${kpiFilter===key?'active':''}" data-filter="${key}" aria-pressed="${kpiFilter===key}"><span class="kpi-label">${label}</span><span class="kpi-value">${snapshot.orders.filter(o=>o[key]).length.toString().padStart(2,'0')}</span><span class="kpi-foot">${key==='active'?'До подписания приёмки':key==='overdue'?'От первоначального срока':key==='low_margin'?`Порог ${snapshot.low_margin_threshold}%`:'Проверить на планёрке'} ↗</span></button>`).join('');
  const orders = filtered();
  const attention = orders.filter(o=>o.overdue || o.open_problem || o.delay_risk || o.incomplete || o.low_margin || o.data_error);
  $('attention-count').textContent = attention.length;
  $('attention').innerHTML = attention.length ? attention.map(o=>`<tr><td><button class="order-link" data-order="${o.id}">${esc(o.order_number)} ↗</button></td><td>${tags(o)}</td><td>${esc(o.stage_executor)}</td><td>${esc(o.next_action)}</td><td>${date(o.next_action_due)}</td></tr>`).join('') : '<tr><td colspan="5">По выбранным фильтрам нет заказов, требующих внимания.</td></tr>';
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
    if (!Array.isArray(data.orders) || !Array.isArray(data.stages) || !data.demo_date || (mode==='backend' && data.source!=='backend')) throw new Error('Invalid response');
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
  $('simulation-notice').hidden = $('mode').value !== 'simulation';
  $('data-source').textContent='Загрузка выбранного источника…';
  refresh();
});
for(const key of ['stage','sales_point','stage_executor','problem']) $(key).addEventListener('change',render);
$('reset').addEventListener('click',()=>{kpiFilter='';for(const key of ['stage','sales_point','stage_executor','problem']) $(key).value='';render();});
document.addEventListener('click',event=>{
  const kpi=event.target.closest('[data-filter]'); if(kpi){kpiFilter=kpiFilter===kpi.dataset.filter?'':kpi.dataset.filter;render();}
  const card=event.target.closest('[data-order]'); if(card)showOrder(Number(card.dataset.order));
});
$('close-details').addEventListener('click',()=>$('details').close());
$('details').addEventListener('click',event=>{if(event.target===$('details')){const r=$('details').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('details').close();}});
$('simulate').addEventListener('click',()=>{
  if($('mode').value!=='simulation'||!snapshot)return;
  const order=snapshot.orders.find(o=>o.id===1);
  Object.assign(order,{problem_type:'Комплектация',problem_comment:'Отсутствует фасад 600 мм (имитация)',problem_help_needed:'Согласовать доставку фасада',problem_status:'open',open_problem:true,next_action:'Согласовать доставку фасада'});
  order.history.unshift({source:'simulation',actor_ref:'Учебный монтажник',created_at:new Date().toISOString(),comment:'Имитация сообщения: отсутствует фасад 600 мм. Telegram и рабочая база не использовались.'});
  render();showOrder(order.id);
});
refresh();
