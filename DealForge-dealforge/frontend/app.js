window.addEventListener('error', (event) => {
  const el = document.getElementById('toast');
  if (el) { el.textContent = `Frontend error: ${event.message}`; el.classList.add('show'); }
  console.error(event.error || event.message);
});

const qs = (s) => document.querySelector(s);
const qsa = (s) => Array.from(document.querySelectorAll(s));
const sessionId = localStorage.getItem('dealforge_session_id') || `browser-${Date.now()}`;
localStorage.setItem('dealforge_session_id', sessionId);

const state = {
  apiBase: window.DEALFORGE_API_BASE || 'http://127.0.0.1:8000',
  connected: false,
  selectedReport: localStorage.getItem('dealforge_selected_report') || 'executive',
  approvals: [],
  localChat: JSON.parse(localStorage.getItem('dealforge_chat') || '[]'),
  activity: JSON.parse(localStorage.getItem('dealforge_activity') || '[]'),
  editingApprovalId: null,
  data: { overview: {}, pipeline: {}, dealPipeline: {}, taskStats: {}, tasks: [], companies: [], contacts: [], deals: [], leads: [], kanban: {} },
};

const titles = {
  home: ['Home', 'Executive CRM overview and operational priorities.'],
  assistant: ['CRM Assistant', 'Sales updates, CRM lookup, reporting, and human approval.'],
  dashboard: ['Dashboard', 'Live CRM visibility from PostgreSQL.'],
  approvals: ['Approvals', 'Pending queue and decision history.'],
  pipeline: ['Pipeline', 'Sales funnel grouped by lead status.'],
  leads: ['Leads', 'Lead lifecycle, priority, ownership, and context.'],
  companies: ['Companies', 'B2B account records.'],
  contacts: ['Contacts', 'People linked to accounts.'],
  deals: ['Deals', 'Opportunity tracking and revenue.'],
  tasks: ['Tasks', 'Follow-ups and reminders.'],
  reports: ['Reports', 'Visual manager reports with local saving and PDF export.'],
  settings: ['Settings', 'Production readiness checks.'],
};

const editFields = [
  ['company_name', 'Company'], ['contact_name', 'Contact'], ['lead_id', 'Lead ID'], ['new_status', 'Lead status'],
  ['deal_stage', 'Deal stage'], ['interest', 'Interest'], ['deal_value', 'Deal value'], ['task_title', 'Next action'],
  ['due_date', 'Due date'], ['priority', 'Priority'], ['activity_notes', 'Activity notes'], ['owner_name', 'Owner']
];

const reportDefs = {
  executive: { label: 'Executive', title: 'Manager Briefing', subtitle: 'Full business snapshot with KPI cards, pipeline, tasks, approvals, and recommendations.' },
  pipeline: { label: 'Pipeline', title: 'Pipeline Performance Report', subtitle: 'Lead status distribution and revenue movement by deal stage.' },
  tasks: { label: 'Tasks', title: 'Task Health Report', subtitle: 'Follow-up execution, open workload, and completion visibility.' },
  approvals: { label: 'Approvals', title: 'Approval Governance Report', subtitle: 'Human-in-the-loop audit status for AI-generated CRM updates.' },
};

function saveChat(){ localStorage.setItem('dealforge_chat', JSON.stringify(state.localChat.slice(-100))); }
function saveActivity(){ localStorage.setItem('dealforge_activity', JSON.stringify(state.activity.slice(0, 150))); }
function toast(text){ const t=qs('#toast'); if(!t) return; t.textContent=text; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),3200); }
function escapeHtml(v){ return String(v ?? '').replace(/[&<>'"]/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;' }[m])); }
function fmtMoney(v){ return new Intl.NumberFormat('en-US',{style:'currency',currency:'SAR',maximumFractionDigits:0}).format(Number(v||0)); }
function prettyKey(k){ return String(k||'').replace(/_/g,' ').replace(/\b\w/g,x=>x.toUpperCase()); }

function parseMaybeJson(value){
  if(value == null) return {};
  if(typeof value === 'object') return value;
  if(typeof value !== 'string') return {};
  const text=value.trim();
  if(!text) return {};
  try { return JSON.parse(text); } catch { return {}; }
}

function normalizeExtracted(raw){
  const parsed=parseMaybeJson(raw);
  const value=(parsed && Object.keys(parsed).length) ? parsed : (raw || {});
  if(value?.entities) return {...value, ...value.entities};
  return value || {};
}

function mergeDisplayPayload(res={}){
  const proposedUpdate=normalizeExtracted(res.proposed_update || {});
  const extracted=normalizeExtracted(res.extracted_data || res.extracted || res.entities || {});
  return {...extracted, ...proposedUpdate};
}

function getResponseType(res={}){
  return String(res.type || res.route_to || res.agent || '').toLowerCase();
}

function setStatus(ok,msg){ state.connected=ok; qs('#statusDot').className=`dot ${ok?'connected':'error'}`; qs('#apiStatus').textContent=msg; }
function logActivity(type,title,detail=''){ state.activity.unshift({type,title,detail,time:new Date().toISOString()}); saveActivity(); }

async function api(path, options={}){
  const res = await fetch(`${state.apiBase.replace(/\/$/,'')}${path}`, { headers:{'Content-Type':'application/json'}, ...options });
  if(!res.ok){ let detail=''; try{ detail=JSON.stringify(await res.json()); }catch{ detail=await res.text(); } throw new Error(`${res.status} ${res.statusText}${detail?` - ${detail}`:''}`); }
  return res.json();
}
async function getSafe(path,fallback){ try{return await api(path);}catch(e){return fallback;} }

function initNavigation(){
  qsa('.nav button').forEach(btn=>btn.onclick=()=>openPage(btn.dataset.page));
  bindPageLinks();
}
function openPage(page){
  qsa('.nav button,.page').forEach(x=>x.classList.remove('active'));
  const btn=qs(`.nav button[data-page="${page}"]`), el=qs(`#${page}`);
  if(btn) btn.classList.add('active'); if(el) el.classList.add('active');
  qs('#pageTitle').textContent=titles[page][0]; qs('#pageSub').textContent=titles[page][1];
  renderAll();
}
function bindPageLinks(){ qsa('[data-go]').forEach(b=>b.onclick=()=>openPage(b.dataset.go)); }

async function healthCheck(){ try{ await api('/test-db'); setStatus(true,'Backend connected'); return true; } catch{ setStatus(false,'Backend unavailable'); return false; } }
async function refreshAll(){
  await healthCheck();
  state.data.overview = await getSafe('/dashboard/overview', {});
  state.data.pipeline = await getSafe('/dashboard/pipeline', state.data.overview.pipeline || {});
  state.data.dealPipeline = await getSafe('/deals/pipeline', {});
  state.data.taskStats = await getSafe('/dashboard/tasks', {});
  state.data.tasks = await getSafe('/tasks', []);
  state.data.companies = await getSafe('/companies', []);
  state.data.contacts = await getSafe('/contacts', []);
  state.data.deals = await getSafe('/deals', []);
  state.data.leads = await getSafe('/leads', []);
  state.data.kanban = await getSafe('/kanban', groupByStatus(state.data.leads));
  const backendApprovals = await getSafe('/approvals', []);
  const seen = new Set();
  state.approvals = (backendApprovals || []).map(a=>{
    const proposedUpdate = normalizeExtracted(a.proposed_update || {});
    const extracted = {...normalizeExtracted(a.extracted_data || {}), ...proposedUpdate};
    return {
      id:a.pending_id,
      status:a.approval_status || 'Pending',
      message:a.user_input || '',
      extracted,
      proposed_update:proposedUpdate,
      createdAt:a.created_at,
      approvedAt:a.approved_at,
      approvedBy:a.approved_by,
      raw:a
    };
  }).filter(a=>a.id && !seen.has(a.id) && seen.add(a.id));
  renderAll();
}

function groupByStatus(leads){ return (leads||[]).reduce((acc,l)=>{ const k=l.status||'Unknown'; (acc[k]||=[]).push(l); return acc; },{}); }
function addChat(role,content,meta={}){ state.localChat.push({role,content,meta,time:new Date().toISOString()}); saveChat(); renderChat(); }
function renderChat(){
  const chat=qs('#chat'); if(!chat) return;
  if(!state.localChat.length){ state.localChat.push({role:'ai',content:'DealForge is ready. Send a sales update, CRM lookup, or reporting request. Database changes will be held for human approval before writing to PostgreSQL.',time:new Date().toISOString()}); saveChat(); }
  chat.innerHTML = state.localChat.map(renderMessage).join(''); chat.scrollTop=chat.scrollHeight; bindApprovalButtons();
}
function renderMessage(m){
  const roleName=m.role==='user'?'You':m.role==='system'?'System notice':'DealForge';
  let html=`<div class="msg ${m.role==='user'?'user':m.role==='system'?'system':'ai'}"><div class="title">${roleName}</div>${formatText(m.content)}`;
  if(m.meta?.extracted) html+=extractionHtml(m.meta.extracted,m.meta.pendingId);
  return html+'</div>';
}
function formatText(content){
  const lines=String(content||'').split('\n').filter(l=>l.trim());
  if(!lines.length) return '';
  if(lines.length===1) return `<div>${escapeHtml(lines[0])}</div>`;
  return `<div>${escapeHtml(lines[0])}</div><ul>${lines.slice(1).map(l=>`<li>${escapeHtml(l.replace(/^[-•]\s*/,''))}</li>`).join('')}</ul>`;
}
function field(k,v){ return `<div class="field"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v || '—')}</strong></div>`; }
function normalizeExtractionForDisplay(ex={}){
  const value = normalizeExtracted(ex);
  return {
    intent:value.intent||value.detected_intent||value.action||'CRM update',
    company:value.company_name||value.company||'',
    contact:value.contact_name||value.full_name||'',
    lead:value.lead_id||'',
    stage:value.new_status||value.status||value.lead_status||value.deal_stage||'',
    interest:value.interest||value.product_interest||'',
    value:value.deal_value?fmtMoney(value.deal_value):'',
    next:value.next_action||value.task_title||'',
    due:value.due_date||'',
    priority:value.priority||'',
    activity:value.activity_notes||'',
  };
}
function extractionHtml(ex,pendingId){
  const d=normalizeExtractionForDisplay(ex);
  return `<div class="crm-card"><h4>CRM action preview</h4><div class="fields">${field('Intent',d.intent)}${field('Company',d.company)}${field('Contact',d.contact)}${field('Lead',d.lead)}${field('Status / Stage',d.stage)}${field('Interest',d.interest)}${field('Value',d.value)}${field('Next action',d.next)}${field('Due date',d.due)}${field('Priority',d.priority)}${field('Activity notes',d.activity)}</div>${pendingId?`<div class="approval-actions"><button class="btn-primary" data-approve="${pendingId}">Approve</button><button class="btn-muted" data-modify="${pendingId}">Edit</button><button class="btn-danger" data-reject="${pendingId}">Reject</button></div>`:''}</div>`;
}
function renderExtraction(){
  const pending=state.approvals.find(a=>String(a.status).toLowerCase()==='pending');
  qs('#activeExtraction').innerHTML=pending?extractionHtml(pending.extracted,null):'<div class="empty-state">No pending CRM action. Send a sales message in the assistant.</div>';
  qs('#pendingCount').textContent=state.approvals.filter(a=>String(a.status).toLowerCase()==='pending').length;
  qs('#openTaskCount').textContent=openTasks().length;
  qs('#pipelineValue').textContent=fmtMoney(totalPipelineValue());
}

async function submitMessage(event){
  event.preventDefault(); const input=qs('#messageInput'); const msg=input.value.trim(); if(!msg) return; input.value='';
  addChat('user',msg); state.localChat.push({role:'ai',content:'Processing your CRM request…',time:new Date().toISOString()}); renderChat();
  try{ const res=await api('/agent/chat',{method:'POST',body:JSON.stringify({session_id:sessionId,message:msg})}); state.localChat.pop(); handleAgentResponse(res,msg); logActivity('agent_message','Agent request processed',msg); await refreshAll(); }
  catch(e){ state.localChat.pop(); addChat('system',`Backend request failed. Confirm FastAPI is running, PostgreSQL is connected, and OPENAI_API_KEY is set. ${e.message}`); logActivity('error','Backend request failed',e.message); }
}
function handleAgentResponse(res,originalMessage){
  const responseType=getResponseType(res);
  const extracted=mergeDisplayPayload(res);

  if(res.requires_clarification || responseType==='clarification' || responseType==='ask_clarification'){
    addChat('ai',res.clarification_question||res.message||'I need one clarification before continuing.',{extracted});
    return;
  }

  if((res.requires_approval || res.needs_approval || responseType==='approval_required' || res.pending_id) && res.pending_id){
    addChat('ai',buildApprovalText(res,originalMessage),{extracted,pendingId:res.pending_id});
    toast('Approval required before writing to CRM');
    return;
  }

  if(responseType==='report' || responseType==='read_result' || responseType==='read' || responseType==='enrichment' || res.agent==='reporting_agent' || res.tool_result || res.report || res.result || res.data){
    addChat('ai',buildReadableReportResponse(res));
    if(responseType==='report') openPage('reports');
    return;
  }

  addChat('ai',res.message||'The request was completed. CRM views are refreshed.');
}

function buildApprovalText(res){
  const lines=['Review required before database write.'];

  if(res.message) lines.push(res.message);

  if(Array.isArray(res.proposed_actions) && res.proposed_actions.length){
    res.proposed_actions.forEach((action,i)=>{
      lines.push(`${i+1}. ${prettyKey(action.action_type || 'CRM action')}`);
      const data=action.data||{};
      Object.entries(data).forEach(([k,v])=>{
        if(v!==undefined && v!==null && v!=='') lines.push(`   ${prettyKey(k)}: ${typeof v==='object'?JSON.stringify(v):v}`);
      });
    });
  } else {
    lines.push(plainSummary(res.proposed_update || 'A CRM update is ready for review.'));
  }

  lines.push('Use Approve, Edit, or Reject inside this chat card.');
  return lines.join('\n');
}

function plainSummary(value){
  const parsed=parseMaybeJson(value);
  const obj=(parsed && Object.keys(parsed).length) ? parsed : value;
  if(typeof obj==='string') return obj;
  if(!obj||typeof obj!=='object') return '';
  return Object.entries(obj).map(([k,v])=>`${prettyKey(k)}: ${typeof v==='object'?JSON.stringify(v):v}`).join('\n');
}

function buildReadableReportResponse(res){
  const data=res.tool_result?.result||res.result||res.report||res.data||{};
  const lines=[res.message||'CRM response completed.'];

  if(Array.isArray(data)){
    data.slice(0,6).forEach((row,i)=>lines.push(`${i+1}. ${Object.entries(row).map(([k,v])=>`${prettyKey(k)}: ${v}`).join(', ')}`));
  } else if(typeof data==='object'&&data){
    Object.entries(data).slice(0,8).forEach(([k,v])=>lines.push(`${prettyKey(k)}: ${typeof v==='object'?plainSummary(v):v}`));
  }

  return lines.join('\n');
}
function bindApprovalButtons(){ qsa('[data-approve]').forEach(b=>b.onclick=()=>decision(Number(b.dataset.approve),'approve')); qsa('[data-reject]').forEach(b=>b.onclick=()=>decision(Number(b.dataset.reject),'reject')); qsa('[data-modify]').forEach(b=>b.onclick=()=>openEditDialog(Number(b.dataset.modify))); }
async function decision(id,decisionValue,editedData=null){
  try{ const body={pending_id:id,decision:decisionValue,decided_by:'frontend_user'}; if(editedData) body.edited_data=editedData; const res=await api('/agent/decision',{method:'POST',body:JSON.stringify(body)}); addChat('ai',humanDecisionMessage(decisionValue,res)); logActivity('approval',`Approval ${decisionValue}`,`Pending ID ${id}`); await refreshAll(); }
  catch(e){ toast(`Approval failed: ${e.message}`); logActivity('error','Approval failed',e.message); }
}
function humanDecisionMessage(value,res){ if(value==='approve') return res.message||'Approved. The CRM update has been executed against PostgreSQL.'; if(value==='edit') return res.message||'Edited update submitted to the approval workflow.'; return res.message||'Rejected. No CRM database write was executed.'; }
function openEditDialog(id){
  const approval=state.approvals.find(a=>a.id===id); if(!approval) return toast('Approval item was not found.'); state.editingApprovalId=id; const extracted=approval.extracted||{};
  qs('#editFields').innerHTML=editFields.map(([key,label])=>`<label>${escapeHtml(label)}<input name="${escapeHtml(key)}" value="${escapeHtml(extracted[key] || '')}" /></label>`).join(''); qs('#editDialog').showModal();
}
function submitEditDialog(e){ e.preventDefault(); const data=Object.fromEntries(new FormData(e.target).entries()); Object.keys(data).forEach(k=>{ if(data[k]==='') delete data[k]; }); qs('#editDialog').close(); decision(state.editingApprovalId,'edit',data); }

function openTasks(){ return (state.data.tasks||[]).filter(t=>!['completed','cancelled'].includes(String(t.status||'').toLowerCase())); }
function totalPipelineValue(){ return (state.data.deals||[]).reduce((s,d)=>s+Number(d.deal_value||0),0); }
function normalizeChartData(obj){ return Object.fromEntries(Object.entries(obj||{}).map(([k,v])=>[k,Array.isArray(v)?v.length:v])); }
function renderBars(selector,obj){ const el=qs(selector); if(!el) return; const entries=Object.entries(obj||{}); if(!entries.length){ el.innerHTML='<div class="empty-state">No backend data yet.</div>'; return; } const max=Math.max(...entries.map(([,v])=>Number(v)||0),1); el.innerHTML=entries.map(([k,v])=>`<div class="bar-row"><span>${escapeHtml(k)}</span><div class="bar-track"><div class="bar-fill" style="width:${((Number(v)||0)/max)*100}%"></div></div><strong>${escapeHtml(v)}</strong></div>`).join(''); }
function table(rows,cols,actions){ if(!rows?.length) return '<div class="empty-state">No records found. Seed the database or create records through the agent.</div>'; return `<table class="table"><thead><tr>${cols.map(c=>`<th>${escapeHtml(c[0])}</th>`).join('')}${actions?'<th>Action</th>':''}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${escapeHtml(formatCell(r[c[1]],c[1]))}</td>`).join('')}${actions?actions(r):''}</tr>`).join('')}</tbody></table>`; }
function formatCell(v,key){ if(v==null||v==='') return '—'; if(String(key).includes('value')) return fmtMoney(v); return v; }

function renderHome(){
  const o=state.data.overview||{}, pending=state.approvals.filter(a=>String(a.status).toLowerCase()==='pending'), tasks=openTasks(), deals=state.data.deals||[];
  const won=deals.filter(d=>String(d.deal_stage||'').toLowerCase()==='won').length || o.won_deals || 0;
  qs('#homeKpis').innerHTML=[['Pipeline Value',fmtMoney(totalPipelineValue())],['Open Deals',deals.filter(d=>!['won','lost'].includes(String(d.deal_stage||'').toLowerCase())).length||o.total_deals||0],['Pending Approvals',pending.length],['Open Tasks',tasks.length],['Total Leads',o.total_leads??(state.data.leads||[]).length],['Won Deals',won],['Companies',o.total_companies??(state.data.companies||[]).length],['Contacts',o.total_contacts??(state.data.contacts||[]).length]].map(([k,v])=>`<div class="kpi"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('');
  qs('#pipelineTotal').textContent=`${(state.data.leads||[]).length} leads`; renderBars('#homePipeline',normalizeChartData(state.data.pipeline||o.pipeline||groupByStatus(state.data.leads||[])));
  const recs=[]; if(pending.length) recs.push(['Approval blocker',`${pending.length} AI-generated CRM update${pending.length>1?'s are':' is'} waiting for a human decision.`,'assistant']); if(tasks.length) recs.push(['Follow-up workload',`${tasks.length} open task${tasks.length>1?'s':' '} need attention.`,'tasks']); const newLeads=(state.data.leads||[]).filter(l=>String(l.status||'').toLowerCase().includes('new')).length; if(newLeads) recs.push(['Lead qualification',`${newLeads} new lead${newLeads>1?'s':' '} should be qualified or routed.`,'leads']); if(!recs.length) recs.push(['CRM clear','No urgent approval or task blockers were found.','dashboard']);
  qs('#recommendations').innerHTML=recs.map(([t,d,p])=>`<div class="recommendation"><div><strong>${escapeHtml(t)}</strong><p>${escapeHtml(d)}</p></div><button data-go="${p}">Open</button></div>`).join('');
  qs('#homeApprovals').innerHTML=pending.length?pending.slice(0,4).map(a=>{const d=normalizeExtractionForDisplay(a.extracted||{});return `<div class="list-item"><div><strong>${escapeHtml(d.company||d.contact||d.intent)}</strong><p>${escapeHtml(a.message||a.proposed_update||'Pending CRM action')}</p></div><span class="status-pill Pending">Pending</span></div>`}).join(''):'<div class="empty-state">No pending approvals.</div>';
  qs('#homeActivity').innerHTML=state.activity.length?state.activity.slice(0,5).map(a=>`<div class="list-item"><div><strong>${escapeHtml(a.title)}</strong><p>${escapeHtml(a.detail||prettyKey(a.type))}</p></div><small>${escapeHtml(new Date(a.time).toLocaleString())}</small></div>`).join(''):'<div class="empty-state">No local work recorded yet.</div>'; bindPageLinks();
}
function renderDashboard(){
  const o=state.data.overview||{}; qs('#kpis').innerHTML=[['Total Leads',o.total_leads??(state.data.leads||[]).length],['Companies',o.total_companies??(state.data.companies||[]).length],['Contacts',o.total_contacts??(state.data.contacts||[]).length],['Total Deals',o.total_deals??(state.data.deals||[]).length],['Won Deals',o.won_deals??'—'],['Pipeline Value',fmtMoney(totalPipelineValue())],['Revenue',fmtMoney(o.total_revenue)],['Pending Tasks',o.pending_tasks??openTasks().length]].map(([k,v])=>`<div class="kpi"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('');
  renderBars('#pipelineChart',normalizeChartData(state.data.pipeline||o.pipeline||{})); renderBars('#taskChart',state.data.taskStats||{});
  qs('#opsSnapshot').innerHTML=[['Database source','PostgreSQL via FastAPI'],['Agent control','Approval required before writes'],['Session memory',sessionId],['Report storage','Browser localStorage + backend local_reports'],['Frontend mode','Production-style static app'],['API health',state.connected?'Connected':'Unavailable']].map(([k,v])=>`<div class="snapshot-card"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('');
}
function renderApprovals(){
  const pending=state.approvals.filter(a=>String(a.status).toLowerCase()==='pending'); const history=state.approvals.filter(a=>String(a.status).toLowerCase()!=='pending');
  const item=(a)=>{ const d=normalizeExtractionForDisplay(a.extracted||{}); const title=d.company||d.contact||d.intent||'CRM update'; const details=[d.contact&&`Contact: ${d.contact}`,d.stage&&`Stage: ${d.stage}`,d.value&&`Value: ${d.value}`,d.next&&`Next: ${d.next}`,a.message&&`Source: ${a.message}`].filter(Boolean).join(' • '); return `<div class="history-item"><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(details || a.proposed_update || 'CRM action recorded')}</p><small>${escapeHtml(a.createdAt || '')}</small></div><span class="status-pill ${escapeHtml(a.status)}">${escapeHtml(a.status)}</span></div>`; };
  qs('#approvalList').innerHTML=`<div class="approval-section"><h4>Pending review</h4>${pending.length?pending.map(item).join(''):'<div class="empty-state">No pending approvals. New approval actions appear in the CRM Assistant chat.</div>'}</div><div class="approval-section"><h4>Decision history</h4>${history.length?history.map(item).join(''):'<div class="empty-state">No completed approval decisions yet.</div>'}</div>`;
}
function renderTables(){
  qs('#leadsTable').innerHTML=table(state.data.leads,[['ID','lead_id'],['Company','company_name'],['Contact','contact_name'],['Status','status'],['Interest','interest'],['Priority','priority'],['Owner','owner_name']]);
  qs('#companiesTable').innerHTML=table(state.data.companies,[['ID','company_id'],['Company','company_name'],['Industry','industry'],['Size','size'],['Location','location'],['Website','website']]);
  qs('#contactsTable').innerHTML=table(state.data.contacts,[['ID','contact_id'],['Company ID','company_id'],['Name','full_name'],['Email','email'],['Phone','phone'],['Job Title','job_title']]);
  qs('#dealsTable').innerHTML=table(state.data.deals,[['ID','deal_id'],['Name','deal_name'],['Value','deal_value'],['Stage','deal_stage'],['Probability','probability'],['Close Date','expected_close_date']]);
  qs('#tasksTable').innerHTML=table(state.data.tasks,[['ID','task_id'],['Lead','lead_id'],['Task','task_title'],['Due','due_date'],['Status','status'],['Priority','priority']],r=>`<td>${String(r.status).toLowerCase()==='completed'?'<span class="status-pill Approved">Completed</span>':`<button class="btn-muted" data-complete-task="${r.task_id}">Complete</button>`}</td>`);
  qsa('[data-complete-task]').forEach(b=>b.onclick=async()=>{ try{ await api(`/tasks/${b.dataset.completeTask}?status=Completed`,{method:'PUT'}); toast('Task marked completed'); await refreshAll(); }catch(e){ toast(`Task update failed: ${e.message}`); } });
}
function renderKanban(){ const board=state.data.kanban||{}; qs('#kanban').innerHTML=Object.entries(board).length?Object.entries(board).map(([status,items])=>`<div class="kanban-col"><h4>${escapeHtml(status)} <span class="status-pill">${items.length}</span></h4>${items.map(l=>`<div class="kanban-card"><strong>${escapeHtml(l.company_name||l.contact_name||`Lead #${l.lead_id}`)}</strong><p>${escapeHtml(l.interest||'No interest recorded')}</p><p>${escapeHtml(l.priority||'Normal')} priority</p></div>`).join('')}</div>`).join(''):'<div class="empty-state">No pipeline records found.</div>'; }

function reportData(){
  const pending=state.approvals.filter(a=>String(a.status).toLowerCase()==='pending').length, approved=state.approvals.filter(a=>String(a.status).toLowerCase().includes('approved')).length, rejected=state.approvals.filter(a=>String(a.status).toLowerCase().includes('reject')).length;
  const o=state.data.overview||{}; const tasks=openTasks();
  const recs=[]; if(pending) recs.push(`Review ${pending} pending approval item${pending>1?'s':''} from the CRM Assistant.`); if(tasks.length) recs.push(`Close or reschedule ${tasks.length} open task${tasks.length>1?'s':''}.`); if(totalPipelineValue()>0) recs.push(`Monitor pipeline exposure of ${fmtMoney(totalPipelineValue())}.`); if(!recs.length) recs.push('No urgent CRM blockers were detected.');
  return { generated_at:new Date().toISOString(), kpis:{'Total Leads':o.total_leads??state.data.leads.length,'Companies':o.total_companies??state.data.companies.length,'Contacts':o.total_contacts??state.data.contacts.length,'Deals':o.total_deals??state.data.deals.length,'Pipeline Value':fmtMoney(totalPipelineValue()),'Revenue':fmtMoney(o.total_revenue),'Open Tasks':tasks.length,'Pending Approvals':pending}, pipeline:normalizeChartData(state.data.pipeline||{}), dealPipeline:normalizeChartData(state.data.dealPipeline||{}), taskHealth:state.data.taskStats||{}, approvals:{Pending:pending,Approved:approved,Rejected:rejected}, recommendations:recs, topLeads:(state.data.leads||[]).slice(0,8).map(l=>({name:l.company_name||l.contact_name||`Lead #${l.lead_id}`,status:l.status||'—',priority:l.priority||'—',owner:l.owner_name||'—'})) };
}
function renderReportCatalog(){ qs('#reportCatalog').innerHTML=Object.entries(reportDefs).map(([key,def])=>`<div class="report-tile ${state.selectedReport===key?'active':''}" data-report="${key}"><span>${def.label}</span><strong>${def.title}</strong><p>${def.subtitle}</p></div>`).join(''); qsa('[data-report]').forEach(t=>t.onclick=()=>{ state.selectedReport=t.dataset.report; localStorage.setItem('dealforge_selected_report',state.selectedReport); renderReport(); }); }
function renderReport(){ renderReportCatalog(); const r=reportData(), def=reportDefs[state.selectedReport]; qs('#reportTitle').textContent=def.title; qs('#reportSubtitle').textContent=def.subtitle; const kpis=Object.entries(r.kpis).map(([k,v])=>`<div class="kpi"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('');
  const executive=`<div class="report-cover"><div><span class="eyebrow">DealForge report</span><h2>${escapeHtml(def.title)}</h2><p>Generated ${escapeHtml(new Date(r.generated_at).toLocaleString())}. This report combines CRM health, pipeline distribution, task workload, approval governance, and manager recommendations.</p></div><strong>${escapeHtml(r.kpis['Pipeline Value'])}</strong></div><div class="report-kpis">${kpis}</div><div class="report-mini-grid"><div class="report-section"><h4>Lead Pipeline</h4><div class="bar-chart" id="reportPipeline"></div></div><div class="report-section"><h4>Task Health</h4><div class="bar-chart" id="reportTasks"></div></div></div><div class="report-section"><h4>Manager Recommendations</h4><div class="stack-list">${r.recommendations.map(x=>`<div class="list-item"><strong>${escapeHtml(x)}</strong></div>`).join('')}</div></div><div class="report-section report-table"><h4>Lead Snapshot</h4>${table(r.topLeads,[['Lead','name'],['Status','status'],['Priority','priority'],['Owner','owner']])}</div>`;
  const pipeline=`<div class="report-cover"><div><span class="eyebrow">Pipeline report</span><h2>Pipeline Performance</h2><p>Lead funnel and deal-stage movement for sales review.</p></div><strong>${escapeHtml(r.kpis['Pipeline Value'])}</strong></div><div class="report-mini-grid"><div class="report-section"><h4>Lead Status</h4><div class="bar-chart" id="reportPipeline"></div></div><div class="report-section"><h4>Deal Stages</h4><div class="bar-chart" id="reportDeals"></div></div></div><div class="report-section report-table"><h4>Lead Snapshot</h4>${table(r.topLeads,[['Lead','name'],['Status','status'],['Priority','priority'],['Owner','owner']])}</div>`;
  const tasks=`<div class="report-cover"><div><span class="eyebrow">Task report</span><h2>Task Health</h2><p>Follow-up workload and completion status.</p></div><strong>${escapeHtml(r.kpis['Open Tasks'])} open</strong></div><div class="report-kpis">${kpis}</div><div class="report-section"><h4>Task Distribution</h4><div class="bar-chart" id="reportTasks"></div></div>`;
  const approvals=`<div class="report-cover"><div><span class="eyebrow">Governance report</span><h2>Approval Audit</h2><p>Human-in-the-loop decision history for AI-generated CRM operations.</p></div><strong>${escapeHtml(r.kpis['Pending Approvals'])} pending</strong></div><div class="report-kpis">${Object.entries(r.approvals).map(([k,v])=>`<div class="kpi"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('')}</div><div class="report-section"><h4>Approval Queue</h4>${state.approvals.length?state.approvals.slice(0,12).map(a=>`<div class="history-item"><div><strong>${escapeHtml(normalizeExtractionForDisplay(a.extracted).company||normalizeExtractionForDisplay(a.extracted).intent)}</strong><p>${escapeHtml(a.message||a.proposed_update||'CRM action')}</p></div><span class="status-pill ${escapeHtml(a.status)}">${escapeHtml(a.status)}</span></div>`).join(''):'<div class="empty-state">No approval records found.</div>'}</div>`;
  qs('#reportBox').innerHTML={executive,pipeline,tasks,approvals}[state.selectedReport]||executive; renderBars('#reportPipeline',r.pipeline); renderBars('#reportTasks',r.taskHealth); renderBars('#reportDeals',r.dealPipeline); bindPageLinks();
}
function download(filename,blob){ const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=filename; a.click(); URL.revokeObjectURL(a.href); }
function pdfEscape(v){ return String(v??'').replace(/[()\\]/g,'').replace(/[^\x09\x0A\x0D\x20-\x7E]/g,''); }
function makePdf(){
  const r=reportData(), def=reportDefs[state.selectedReport]; const c=[]; const text=(x,y,v,size=10,b=false)=>c.push(`BT /${b?'F2':'F1'} ${size} Tf ${x} ${y} Td (${pdfEscape(v)}) Tj ET`); const rect=(x,y,w,h,color='0.96 0.98 1')=>c.push(`${color} rg ${x} ${y} ${w} ${h} re f`); rect(0,772,612,70,'0.04 0.12 0.27'); text(40,813,'DealForge',14,true); text(40,792,def.title,21,true); text(40,776,`Generated ${new Date(r.generated_at).toLocaleString()}`,9); text(430,794,r.kpis['Pipeline Value'],18,true);
  Object.entries(r.kpis).slice(0,8).forEach(([k,v],i)=>{const x=40+(i%4)*135,y=700-Math.floor(i/4)*68; rect(x,y,118,48,'0.95 0.97 1'); text(x+10,y+31,k,8); text(x+10,y+12,v,13,true);});
  const drawBars=(title,data,x,y)=>{text(x,y,title,13,true); const entries=Object.entries(data||{}).slice(0,7), max=Math.max(...entries.map(([,v])=>Number(v)||0),1); if(!entries.length) text(x,y-25,'No data available',9); entries.forEach(([k,v],i)=>{const yy=y-25-i*22; text(x,yy+3,k,8); rect(x+105,yy,135,10,'0.90 0.94 0.98'); rect(x+105,yy,135*((Number(v)||0)/max),10,'0.08 0.55 0.85'); text(x+250,yy+1,v,8,true);});};
  drawBars('Lead Pipeline',r.pipeline,40,560); drawBars(state.selectedReport==='pipeline'?'Deal Stages':'Task Health',state.selectedReport==='pipeline'?r.dealPipeline:r.taskHealth,320,560);
  text(40,350,'Approval Governance',13,true); Object.entries(r.approvals).forEach(([k,v],i)=>{rect(40+i*120,310,105,34,i===0?'1 0.95 0.78':i===1?'0.86 0.98 0.9':'1 0.88 0.88'); text(50+i*120,330,k,8); text(50+i*120,314,v,14,true);});
  text(40,260,'Manager Recommendations',13,true); r.recommendations.forEach((rec,i)=>text(55,238-i*18,`- ${rec}`,10)); text(40,155,'Lead Snapshot',13,true); r.topLeads.slice(0,5).forEach((lead,i)=>text(55,134-i*18,`${lead.name} | ${lead.status} | ${lead.priority} | ${lead.owner}`,9));
  const content=c.join('\n'); const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [4 0 R] /Count 1 >>','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R /F2 6 0 R >> >> /Contents 5 0 R >>`,`<< /Length ${content.length} >>\nstream\n${content}\nendstream`,'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>']; let body='%PDF-1.4\n'; const offsets=[0]; objects.forEach((o,i)=>{offsets.push(body.length); body+=`${i+1} 0 obj\n${o}\nendobj\n`;}); const xref=body.length; body+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`+offsets.slice(1).map(n=>`${String(n).padStart(10,'0')} 00000 n `).join('\n')+`\ntrailer << /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`; return new Blob([body],{type:'application/pdf'});
}
async function saveReportSnapshot(){ const payload={generated_at:new Date().toISOString(),report_type:state.selectedReport,report:reportData(),dashboard:state.data,approvals:state.approvals}; localStorage.setItem(`dealforge_report_${Date.now()}`,JSON.stringify(payload)); try{ await api('/reports/save-local',{method:'POST',body:JSON.stringify(payload)}); toast('Report saved locally in browser and backend local_reports'); } catch{ toast('Report saved in browser local storage. Backend save endpoint unavailable.'); } logActivity('report','Report snapshot saved',reportDefs[state.selectedReport].title); }
async function downloadReport(){ await saveReportSnapshot(); download(`DealForge_${reportDefs[state.selectedReport].title.replace(/\s+/g,'_')}_${new Date().toISOString().slice(0,10)}.pdf`,makePdf()); logActivity('report','PDF report downloaded',reportDefs[state.selectedReport].title); }
function renderReadiness(){ qs('#readiness').innerHTML=`<div class="settings-grid">${check('Frontend implements backend workflow',true,'CRM Assistant uses /agent/chat, approval decisions use /agent/decision, and records use dashboard/table endpoints.')}${check('Normal users do not edit JSON',true,'Approvals use forms and cards only.')}${check('Approval actions are in chat',true,'Approve, edit, and reject controls appear inside CRM Assistant response cards, not in the side work item panel.')}${check('Reports are visual and exportable',true,'Report catalog, KPI cards, visual bars, local save, and PDF export are included.')}${check('Activity log removed from navigation',true,'Local activity is used only internally for context, not as a product page.')}${check('FastAPI reachable',state.connected,state.connected?'Backend and database health check passed.':'Start backend and PostgreSQL.')}${check('Production hardening required before public internet',false,'Add authentication, role permissions, HTTPS, restricted CORS, and real deployment environment variables.')}</div>`; }
function check(t,ok,n=''){ return `<div class="check"><span class="dot ${ok?'connected':'error'}"></span><div><strong>${escapeHtml(t)}</strong>${n?`<p class="hint">${escapeHtml(n)}</p>`:''}</div></div>`; }
function renderAll(){ renderChat(); renderExtraction(); renderHome(); renderDashboard(); renderApprovals(); renderTables(); renderKanban(); renderReport(); renderReadiness(); bindPageLinks(); }
function boot(){ initNavigation(); qs('#refreshBtn').onclick=refreshAll; qs('#healthBtn').onclick=async()=>toast(await healthCheck()?'Backend and database are reachable':'Cannot reach backend/database'); qs('#sampleBtn').onclick=()=>{ qs('#messageInput').value='I spoke with Ahmed from GulfTech today. They are interested in AI training for 25 employees. Budget is 80K SAR. Send proposal next Monday and move them to Qualified.'; qs('#messageInput').focus(); }; qs('#clearChatBtn').onclick=()=>{ state.localChat=[]; saveChat(); renderChat(); logActivity('chat','Chat cleared','Local chat history cleared from browser.'); }; qs('#chatForm').onsubmit=submitMessage; qs('#editForm').addEventListener('submit',submitEditDialog); qs('#downloadReport').onclick=downloadReport; qs('#saveReportBtn').onclick=saveReportSnapshot; refreshAll(); }
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',boot):boot();
