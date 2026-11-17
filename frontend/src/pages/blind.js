import {blind,jobs,datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {BlindStatus,BlindSide,IncidentState} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
const badge=s=>'<span class="blind-badge '+esc(s)+'">'+esc(BlindStatus[s]||s)+'</span>';
const steps=a=>{const order=['tuning','locked','unblinded'],idx=a.status==='unblinded'?2:(a.status==='tuning'?0:1);
 return '<div class="blind-steps">'+[['划分调参','按事故编号整组划分，仅开放样本可调参'],['候选锁定','负责人锁定候选分析，参数不再更换'],['揭盲公布','固定参数计算封存部分并公布']].map((s,i)=>'<div class="'+(i<=idx?'on':'')+'">'+esc(s[0])+'<strong>'+(i<idx?'已完成':(i===idx?(a.status==='unblinding'?'揭盲计算中…':(a.status==='unblind_failed'?'计算失败，待重试':(i===2?'已公布':'进行中'))):'待进行'))+'</strong><p>'+esc(s[1])+'</p></div>').join('')+'</div>';};
export async function blindPage(id){
 const [list,allJobs,allDatasets]=await Promise.all([blind.list(),jobs.list(),datasets.list()]);
 workspace.blind=list;
 const admin=session.user.role==='admin';
 if(!id){
  const create=admin?'<section class="panel"><div class="section-title"><h2>划分新盲验活动</h2><span>按事故编号整组划分</span></div><form id="blind-form"><label>活动名称<input name="name" required minlength="2" placeholder="例如：W46 窗口规则盲验"></label><label>封存比例（%）<input type="number" name="sealed_percent" value="40" min="10" max="90" required></label><div class="dataset-checks"><span>纳入批次（同一事故跨批归同侧）</span>'+allDatasets.map(d=>'<label class="check"><input type="checkbox" name="ds" value="'+d.id+'"> '+esc(d.name)+' · '+d.rows+' 条</label>').join('')+'</div><button type="submit" class="primary" '+(!allDatasets.length?'disabled':'')+'>划分并封存 ↗</button><p class="hint">划分即生效：封存事件与结果按越权拒绝，旧批次的分析和下载同步受限；已受理或已揭盲的事故拒绝另开活动复用。</p></form></section>':'';
  return heading('04 / BLIND','盲验活动','复盘调参与留验样本物理隔离：划分、锁定、揭盲全程留痕，杜绝用封存事件挑规则。')+'<div class="blind-grid">'+create+'<section class="panel"><div class="section-title"><h2>活动列表</h2><span>'+list.length+' 个</span></div>'+(list.length?list.map(a=>'<a class="batch-item" href="#/blind/'+a.id+'"><strong>'+esc(a.name)+' '+badge(a.status)+'</strong><span>开放 '+(a.counts.open||0)+' 事故 · 封存 '+(a.counts.sealed||0)+' 事故 · 比例 '+a.sealed_percent+'%</span><small>'+date(a.created_at)+' · '+(a.datasets||[]).map(d=>esc(d.name)).join('、')+'</small></a>').join(''):'<div class="empty">尚无盲验活动。'+(admin?'从左侧划分一个。':'等待负责人划分。')+'</div>')+'</section></div>';
 }
 const a=await blind.get(id),incidents=await blind.incidents(id);
 const candidates=allJobs.filter(j=>j.blind_activity_id===a.id&&j.blind_scope==='open'&&j.status==='completed');
 const candidateJob=allJobs.find(j=>j.id===a.candidate_job_id),sealedJob=allJobs.find(j=>j.id===a.sealed_job_id);
 const candidatePanel=a.status==='tuning'
  ?(admin?'<form id="lock-form"><label>候选分析（开放样本已完成任务）<select name="job_id" required>'+(candidates.map(j=>'<option value="'+j.id+'">#'+j.id+' · '+esc(j.name)+' · '+esc(JSON.stringify(j.params))+'</option>').join('')||'<option value="" disabled>暂无可用候选</option>')+'</select></label><button type="submit" class="primary" '+(!candidates.length?'disabled':'')+'>锁定候选 ↗</button><p class="hint">锁定后参数固定，不再更换；随后可受理揭盲。</p></form>':'<p class="hint">调参进行中：仅开放样本可分析，等待负责人锁定候选。</p>')
  :'<div class="locked-box"><p class="eyebrow">LOCKED CANDIDATE</p><h3>#'+a.candidate_job_id+' · '+esc(candidateJob?candidateJob.name:'候选任务')+'</h3><pre>'+esc(JSON.stringify(a.locked_params,null,2))+'</pre><p class="hint">'+date(a.locked_at)+' 锁定，参数已固定。</p></div>';
 const unblindPanel=
  a.status==='locked'?(admin?'<button class="primary" id="unblind-btn">受理揭盲：以锁定参数计算封存部分 ↗</button><p class="hint">揭盲只受理一次；受理后事故即消费，即使计算失败也不退回可用。</p>':'<p class="hint">候选已锁定，等待负责人受理揭盲。</p>')
  :a.status==='unblinding'?'<p class="hint">封存部分计算中（任务 #'+(a.sealed_job_id||'—')+'）。刷新查看最新状态。</p><button class="button" id="blind-refresh">刷新 ↻</button>'
  :a.status==='unblind_failed'?'<p class="warning">封存计算失败：'+esc(a.error||'未知原因')+'</p>'+(admin?'<button class="primary" id="unblind-btn">重试揭盲（不重复消费事故）↗</button>':'<p class="hint">等待负责人重试。</p>')
  :a.status==='unblinded'?'<div class="locked-box"><p class="eyebrow">UNBLINDED</p><h3>封存结果已公布</h3><p>'+date(a.unblinded_at)+' 以锁定参数完成封存评估（任务 #'+a.sealed_job_id+'）。</p><a class="text-link" href="#/results/'+a.sealed_job_id+'">查看封存评估结果 ↗</a></div>'
  :'';
 return heading('04 / BLIND',a.name,'盲验活动 #'+a.id+' · 封存比例 '+a.sealed_percent+'% · 创建于 '+date(a.created_at),badge(a.status))
  +steps(a)
  +'<div class="metrics"><div><span>开放调参事故</span><strong>'+(a.counts.open||0)+'</strong></div><div><span>封存留验事故</span><strong>'+(a.counts.sealed||0)+'</strong></div><div><span>已受理事故</span><strong>'+(a.counts.accepted||0)+'</strong></div><div><span>已揭盲事故</span><strong>'+(a.counts.unblinded||0)+'</strong></div></div>'
  +'<section class="panel"><div class="section-title"><h2>状态与隔离原因</h2><span>纳入批次：'+(a.datasets||[]).map(d=>esc(d.name)).join('、')+'</span></div>'+(a.isolation||[]).map(r=>'<p class="warning">'+esc(r)+'</p>').join('')+'</section>'
  +'<div class="two-columns"><section class="panel"><div class="section-title"><h2>候选分析</h2></div>'+candidatePanel+'</section><section class="panel"><div class="section-title"><h2>揭盲</h2></div>'+unblindPanel+'</section></div>'
  +'<section class="panel"><div class="section-title"><h2>事故划分明细</h2><span>'+incidents.length+' 个事故 · 同一事故跨批归同侧</span></div>'+table([{key:'incident_id',label:'事故编号'},{key:'side',label:'划分侧'},{key:'state',label:'状态'}],incidents.map(i=>({incident_id:i.incident_id,side:BlindSide[i.side]||i.side,state:IncidentState[i.state]||i.state})),'该活动暂无事故划分。')+'</section>';
}
export function bindBlind(refresh){
 const form=document.querySelector('#blind-form');
 if(form)submit(form,async f=>{const ids=f.getAll('ds').map(Number);if(!ids.length)throw new Error('请至少勾选一个数据批次');const a=await blind.create({name:f.get('name'),sealed_percent:Number(f.get('sealed_percent')),dataset_ids:ids});notify('盲验活动已划分，封存侧即刻隔离');location.hash='#/blind/'+a.id;});
 const lockForm=document.querySelector('#lock-form');
 if(lockForm)submit(lockForm,async f=>{await blind.lock(Number(route_id()),Number(f.get('job_id')));notify('候选已锁定，参数固定');await refresh();});
 document.querySelector('#unblind-btn')?.addEventListener('click',async()=>{try{await blind.unblind(Number(route_id()));notify('揭盲已受理，封存部分计算中');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#blind-refresh')?.addEventListener('click',refresh);
}
function route_id(){return location.hash.replace(/^#\//,'').split('/')[1];}
