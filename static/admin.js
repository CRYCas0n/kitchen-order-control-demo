'use strict';
const $=id=>document.getElementById(id);
const money=v=>v===null||v===undefined?'Нет данных':new Intl.NumberFormat('ru-RU').format(v)+' ₽';
let orders=[];
function current(){const order=orders.find(o=>o.id===Number($('admin-order').value));if(!order)return;$('current').textContent=`Текущая переделка: ${money(order.costs.rework_actual)}. Маржинальный доход: ${money(order.economy.actual?.margin_income??null)}.`;$('rework').value=order.costs.rework_actual??'';}
function busy(value){for(const id of ['save','admin-order','rework'])$(id).disabled=value;}
async function init(){
  busy(true);
  try{
    const response=await fetch('/api/orders',{cache:'no-store',signal:AbortSignal.timeout(12000)});
    if(!response.ok)throw Error();
    orders=await response.json();
    if(!Array.isArray(orders)||!orders.length)throw Error();
    for(const o of orders){const option=document.createElement('option');option.value=o.id;option.textContent=o.order_number+' · '+o.client_alias;$('admin-order').append(option);}
    current();busy(false);
  }catch{$('current').textContent='Не удалось получить заказы. Обновите страницу.';}
}
$('admin-order').addEventListener('change',()=>{current();$('admin-result').hidden=true;});
$('rework-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const orderId=Number($('admin-order').value),value=$('rework').value,result=$('admin-result');
  busy(true);result.hidden=true;
  try{
    const response=await fetch(`/api/admin/orders/${orderId}/rework`,{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'kitchen-control'},body:JSON.stringify({rework_actual:value}),cache:'no-store',signal:AbortSignal.timeout(12000)});
    let data;
    try{data=await response.json();}catch{throw Error('Сервер вернул некорректный ответ. Обновите страницу и проверьте стоимость перед повторным сохранением.');}
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Не удалось сохранить значение. Обновите страницу и проверьте результат.');
    if(data.id!==orderId||!data.costs||!data.economy)throw Error('Некорректное подтверждение. Обновите страницу и проверьте стоимость.');
    orders=orders.map(o=>o.id===data.id?data:o);current();
    result.className='notice';
    result.textContent=`Сохранено: ${data.order_number}. Новый маржинальный доход: ${money(data.economy.actual?.margin_income)}.${data.data_error?' В заказе есть ошибка данных: '+data.data_error:data.low_margin?' Внимание: низкая или отрицательная маржинальность.':''}`;
  }catch(error){
    result.className='notice danger';
    result.textContent=error instanceof TypeError||['TimeoutError','AbortError'].includes(error.name)?'Нет подтверждения от сервера. Обновите страницу и проверьте стоимость перед повторным сохранением.':error.message;
  }finally{result.hidden=false;busy(false);}
});
init();
