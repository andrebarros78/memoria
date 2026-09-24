const state = { items: [] };

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat('pt-BR').format(Number(n || 0));
const dateFmt = (value) => value ? new Date(value).toLocaleString('pt-BR') : '—';

function toast(message, error=false){
  const el = $('toast'); el.textContent = message; el.className = `toast show${error?' error':''}`;
  setTimeout(()=> el.className='toast', 2600);
}

function bootstrapAuth(){
  const frag = new URLSearchParams(location.hash.replace(/^#/,''));
  const browserToken = frag.get('browser_token');
  if(browserToken){
    sessionStorage.setItem('memoryBrowserToken', browserToken);
    history.replaceState(null, '', location.pathname + location.search);
  }
  return { token: sessionStorage.getItem('memoryBrowserToken') || '' };
}

const auth = bootstrapAuth();

async function api(path, options={}){
  const method = (options.method || 'GET').toUpperCase();
  const bodyText = typeof options.body === 'string' ? options.body : '';
  if(!auth.token) throw new Error('Painel bloqueado: abra pelo launcher seguro.');
  const headers = Object.assign({}, options.headers || {}, {Authorization: `Bearer ${auth.token}`});
  const res = await fetch(path, {...options, method, headers});
  let body = null;
  const text = await res.text();
  try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
  if(!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function setHealth(ok, label){
  const wrap = document.querySelector('.health');
  wrap.classList.toggle('ok', ok); $('healthLabel').textContent = label;
}

async function loadSummary(){
  try{
    const s = await api('/v1/dashboard/summary');
    setHealth(s.health === 'OK', s.health === 'OK' ? 'Saudável' : s.health);
    $('total').textContent = fmt(s.memories_total);
    $('permanent').textContent = fmt(s.operator_classes?.PERMANENTE);
    $('reuse').textContent = fmt(s.applications);
    $('successRate').textContent = s.reuse_success_rate == null ? '—' : `${s.reuse_success_rate}%`;
    $('activeCount').textContent = fmt(s.operator_classes?.ATIVA);
    $('archivedCount').textContent = fmt(s.operator_classes?.ARQUIVADA);
    $('discardCount').textContent = fmt(s.operator_classes?.['DESCARTÁVEL']);
    $('protectedCount').textContent = fmt(s.operator_classes?.PROTEGIDA);
    $('learningCount').textContent = fmt(s.learning_items);
    $('retrievalCount').textContent = fmt(s.retrievals);
    $('auditCount').textContent = fmt(s.audit_events);
  }catch(e){ setHealth(false,'Bloqueado'); toast(e.message,true); }
}

function renderRows(){
  const tbody = $('memoryRows');
  if(!state.items.length){ tbody.innerHTML = '<tr><td colspan="5" class="empty">Nenhuma memória encontrada.</td></tr>'; return; }
  tbody.innerHTML = state.items.map(item => {
    const rate = item.success_rate == null ? '—' : `${item.success_rate}%`;
    return `<tr>
      <td><strong>${escapeHtml(item.memory_key)}</strong><br><span class="muted">${escapeHtml(item.content_text || '').slice(0,110)}</span></td>
      <td><span class="badge ${item.operator_class}">${item.operator_class}</span></td>
      <td>${dateFmt(item.last_used_at || item.created_at)}</td>
      <td>${fmt(item.application_count)} · ${rate}</td>
      <td>${Math.round(Number(item.confidence || 0)*100)}%</td>
    </tr>`;
  }).join('');
}

function escapeHtml(v){ return String(v).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }

function renderKeyValueList(targetId, rows){
  const target = $(targetId);
  if(!target) return;
  if(!rows.length){ target.innerHTML = '<div class="empty">Sem dados.</div>'; return; }
  target.innerHTML = rows.map(row => `<div class="v52-row"><span>${escapeHtml(row[0])}</span><strong>${escapeHtml(row[1])}</strong></div>`).join('');
}

async function loadV52Operational(){
  try{
    const data = await api('/v1/dashboard/human-memory');
    const scopes = Object.entries(data.human_identity?.by_scope_label || {}).map(([k,v]) => [k, fmt(v)]);
    renderKeyValueList('humanScopes', scopes);
    const ex = data.retrieval_explainability || {};
    if($('latestTraceBadge')) $('latestTraceBadge').textContent = ex.latest_trace_id ? 'auditável' : 'sem trace';
    renderKeyValueList('latestRetrieval', [
      ['Trace', ex.latest_trace_id || '—'],
      ['Query', ex.latest_query || '—'],
      ['Selecionadas', fmt(ex.latest_selected_count || 0)],
      ['Modos', (ex.latest_modes || []).join(' + ') || '—']
    ]);
    const obs = data.observability || await api('/v1/observability/v52');
    if($('v52ObsStatus')) $('v52ObsStatus').textContent = obs.status || 'UNKNOWN';
    renderKeyValueList('v52ObsBody', [
      ['Contrato', obs.contract || '—'],
      ['Fallback', obs.fallback || '—'],
      ['Traces', fmt(obs.retrieval_traces_total || 0)],
      ['Phoenix paralelo', obs.phoenix_parallel || '—']
    ]);
  }catch(e){
    renderKeyValueList('humanScopes', [['Erro', e.message]]);
    if($('v52ObsStatus')) $('v52ObsStatus').textContent = 'BLOQUEADO';
  }
}

async function loadV53AIIntegration(){
  try{
    const spec = await api('/v1/ai-integration/spec');
    if($('v53AIStatus')) $('v53AIStatus').textContent = spec.contract || 'V5.3';
    renderKeyValueList('v53AIBody', [
      ['Contrato', spec.contract || '—'],
      ['API interna de IA', spec.internal_ai_api_created ? 'sim' : 'não'],
      ['Escrita direta da IA', spec.external_ai_direct_memory_write ? 'sim' : 'não'],
      ['Banco direto da IA', spec.external_ai_direct_database_access ? 'sim' : 'não'],
      ['Tipos aceitos', (spec.allowed_suggestion_types || []).join(' + ') || '—'],
      ['Fluxo', (spec.mandatory_flow || []).slice(0,4).join(' â†’ ') || '—']
    ]);
  }catch(e){
    if($('v53AIStatus')) $('v53AIStatus').textContent = 'BLOQUEADO';
    renderKeyValueList('v53AIBody', [['Erro', e.message]]);
  }
}

async function loadMemories(){
  const params = new URLSearchParams();
  if($('search').value.trim()) params.set('q',$('search').value.trim());
  if($('filterClass').value) params.set('operator_class',$('filterClass').value);
  params.set('limit','200');
  try{ const data = await api(`/v1/memories?${params}`); state.items = data.items || []; renderRows(); }
  catch(e){ state.items=[]; renderRows(); toast(e.message,true); }
}

async function downloadReport(){
  try{
    const path='/v1/reports/operational.md';
    if(!auth.token) throw new Error('Painel bloqueado: abra pelo launcher seguro.');
    const res=await fetch(path,{headers:{Authorization:`Bearer ${auth.token}`}});
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob=await res.blob();
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='MEMORIA_PERMANENTE_OPERATIONAL.md'; a.click();
    setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }catch(e){toast(e.message,true);}
}

$('refreshBtn').addEventListener('click', ()=> Promise.all([loadSummary(),loadMemories(),loadV52Operational(),loadV53AIIntegration()]));
$('filterClass').addEventListener('change', loadMemories);
$('search').addEventListener('keydown', e => { if(e.key==='Enter') loadMemories(); });
const reportLink=document.querySelector('.report-link'); if(reportLink) reportLink.addEventListener('click',e=>{e.preventDefault();downloadReport();});

if(auth.token){ Promise.all([loadSummary(),loadMemories(),loadV52Operational(),loadV53AIIntegration()]); }
else { setHealth(false,'Autenticação necessária'); toast('Abra o painel pelo launcher seguro.',true); }

// P16 governance contract
const UI_GOVERNANCE_SPEC_ENDPOINT = '/v1/ui-governance/spec';
