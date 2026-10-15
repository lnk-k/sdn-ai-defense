const $ = id => document.getElementById(id);
const names = {off:'无防御', threshold:'阈值防御', rf:'随机森林', normal:'正常背景', udp:'UDP 异常', icmp:'ICMP 异常'};
const eventNames = {switch_connected:'交换机连接',switch_disconnected:'交换机断开',block_requested:'请求临时封禁',rule_ack:'交换机确认规则',drop_observed:'观测到实际丢弃',rule_expired:'封禁到期，重新评估',openflow_error:'OpenFlow 错误',stats_timeout:'统计请求超时'};
let data=null, current=0, playing=false, fetching=false;
const fetchJSON = async url => {const r=await fetch(url);if(!r.ok)throw Error('数据暂不可用');return r.json();};
const text = (id,value) => {$(id).textContent=value;};
const fmt = (x,n=2) => Number.isFinite(x)?x.toFixed(n):'未测得';
function addCell(row,value){const td=document.createElement('td');td.textContent=value;row.append(td);}
async function refresh(){
  try{
    const runs=await fetchJSON('/api/runs'), selected=$('run').value;
    $('run').replaceChildren();
    for(const r of runs){const o=document.createElement('option');o.value=r.path;const category={collection:'采集',benchmark:'对照',smoke:'调试',demo:'演示'}[r.path.split('/')[0]]||'实验';o.textContent=`${category} · ${names[r.scenario]} / ${names[r.method]} / ${r.id}${r.status==='failed'?'（失败）':''}`;$('run').append(o);}
    if(runs.some(r=>r.path===selected))$('run').value=selected;
    else {const best=runs.find(r=>r.path.startsWith('benchmark')&&r.scenario==='udp'&&r.method==='rf');if(best)$('run').value=best.path;}
    $('empty').hidden=!!runs.length;$('content').hidden=!runs.length;
    if(runs.length)await load(true);else text('status','等待真实实验数据');
    const results=await fetchJSON('/api/results');$('comparison').replaceChildren();
    for(const g of results.groups||[]){const tr=document.createElement('tr');[names[g.scenario],names[g.method],`${fmt(g.during_attack_mbps.mean)} Mbit/s`,fmt(g.false_blocks.mean,1)].forEach(v=>addCell(tr,v));$('comparison').append(tr);}
    if(!results.groups?.length){const tr=document.createElement('tr');addCell(tr,'对照实验完成后生成结果');$('comparison').append(tr);}
  }catch(e){text('status',e.message);}
}
async function load(reset=false){
  if(fetching||!$('run').value)return;fetching=true;
  try{data=await fetchJSON('/api/run?id='+encodeURIComponent($('run').value));
    const duration=data.metadata.duration||30;$('timeline').max=duration;
    if(reset)current=data.metadata.status==='completed'?duration:Math.max(0,Math.min(duration,Date.now()/1000-(data.metadata.started||Date.now()/1000)));
    text('status',data.metadata.status==='completed'?'实验已完成 · 可回放':data.metadata.status==='failed'?'实验失败 · 请查看日志':'实验进行中');
    render();
  }catch(e){text('status',e.message);}finally{fetching=false;}
}
function render(){
  if(!data)return;const m=data.metadata,start=m.started||0,now=start+current;
  $('timeline').value=current;text('elapsed',`${current.toFixed(1)} / ${m.duration} s`);text('clock',`实验时间 ${current.toFixed(1)} s`);
  const active=now>=m.scenario_started&&now<(m.scenario_ended||Infinity);
  text('phase',!m.started?'拓扑初始化':!m.scenario_started||now<m.scenario_started?'正常业务基线':active?(m.scenario==='normal'?'正常负载':'异常流量持续'):'场景流量停止');
  const candidates=data.samples.filter(s=>s.window_end<=now&&s.window_end>now-2.5&&s.src==='10.0.0.3');
  const latest=Math.max(...candidates.map(s=>s.window_end));
  const recent=candidates.filter(s=>s.window_end===latest);
  text('pps',fmt(recent.length?recent.reduce((s,r)=>s+r.packet_rate,0):NaN,0));
  const interval=data.throughput.find(r=>r.start<=current&&r.end>=current);
  text('throughput',fmt(interval?.mbps));text('method',names[m.method]||m.method);
  const events=data.events.filter(e=>e.time<=now);const block=events.filter(e=>e.kind==='rule_ack'&&e.src==='10.0.0.3').at(-1);
  const expired=events.filter(e=>e.kind==='rule_expired'&&e.src==='10.0.0.3').at(-1);
  const blocked=!!block&&now<block.time+(block.seconds||10)&&(!expired||expired.time<block.time);
  text('defense',m.method==='off'?'仅观察':blocked?'临时封禁中':'监测中');
  $('attack-node').classList.toggle('attacking',active&&m.scenario!=='normal'&&!blocked);$('attack-node').classList.toggle('blocked',blocked);
  text('topology-note',blocked?'s1 已安装高优先级丢弃规则':'控制器每秒采集一次统计');
  $('events').replaceChildren();text('event-count',`${events.length} 条`);
  for(const e of events.slice(-30).reverse()){const el=document.createElement('div');el.className='event';const t=document.createElement('time');t.textContent=`${(e.time-start).toFixed(1)} s`;const b=document.createElement('b');b.textContent=eventNames[e.kind]||e.kind;
    const sub=document.createElement('small');sub.textContent=[e.src,e.dpid?`交换机 s${e.dpid}`:'',e.dropped_packets!==undefined?`已丢弃 ${e.dropped_packets} 包`:''].filter(Boolean).join(' · ');el.append(t,b,sub);$('events').append(el);}
  if(!events.length)text('events','此时刻暂无控制事件');draw();
}
function draw(){
  const canvas=$('chart'),w=canvas.clientWidth,h=canvas.clientHeight,ratio=window.devicePixelRatio||1;
  canvas.width=w*ratio;canvas.height=h*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);
  const left=42,right=w-14,top=18,bottom=h-30,m=data.metadata;
  const groups={1:new Map(),3:new Map()};
  for(const s of data.samples){const n=s.src==='10.0.0.1'?1:s.src==='10.0.0.3'?3:0;if(!n)continue;const t=s.window_end-m.started;groups[n].set(t,(groups[n].get(t)||0)+s.byte_rate*8/1e6);}
  const series=[...Object.values(groups).map(g=>[...g].map(([t,y])=>({t,y}))),data.throughput.map(r=>({t:(r.start+r.end)/2,y:r.mbps}))];
  const ymax=Math.max(12,...series.flat().map(p=>p.y))*1.08;const x=t=>left+t/m.duration*(right-left),y=v=>bottom-v/ymax*(bottom-top);
  if(m.scenario_started){c.fillStyle='rgba(246,184,90,.06)';c.fillRect(x(Math.max(0,m.scenario_started-m.started)),top,x(Math.min(m.duration,(m.scenario_ended||m.started+m.duration)-m.started))-x(Math.max(0,m.scenario_started-m.started)),bottom-top);}
  c.font='10px system-ui';c.strokeStyle='#253347';c.fillStyle='#9aaec6';c.lineWidth=1;
  for(let i=0;i<=4;i++){const yy=top+(bottom-top)*i/4;c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillText((ymax*(1-i/4)).toFixed(0),5,yy+3);}
  for(let i=0;i<=4;i++)c.fillText((m.duration*i/4).toFixed(0)+'s',x(m.duration*i/4)-8,h-9);
  ['#58d6b1','#f6b85a','#78abff'].forEach((color,i)=>{c.strokeStyle=color;c.lineWidth=2;c.beginPath();let first=true;for(const p of series[i]){if(p.t<0||p.t>current)continue;if(first)c.moveTo(x(p.t),y(p.y));else c.lineTo(x(p.t),y(p.y));first=false;}c.stroke();});
  c.strokeStyle='#dce8f7';c.setLineDash([3,5]);c.beginPath();c.moveTo(x(current),top);c.lineTo(x(current),bottom);c.stroke();c.setLineDash([]);
}
$('refresh').onclick=refresh;$('run').onchange=()=>{playing=false;text('play','▶ 回放');load(true);};
$('timeline').oninput=()=>{playing=false;text('play','▶ 回放');current=+$('timeline').value;render();};
$('play').onclick=()=>{if(!data)return;playing=!playing;if(playing&&current>=data.metadata.duration)current=0;text('play',playing?'Ⅱ 暂停':'▶ 回放');};
setInterval(()=>{if(playing&&data){current=Math.min(data.metadata.duration,current+0.1);if(current>=data.metadata.duration){playing=false;text('play','▶ 回放');}render();}},100);
setInterval(()=>{if(['starting','running'].includes(data?.metadata.status)&&!playing)load(true);},2000);
window.addEventListener('resize',()=>{if(data)draw();});refresh();
