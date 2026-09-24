const DEFAULTS={apiUrl:'http://127.0.0.1:8787',tenant:'LEGACY',enabled:true};
const QUEUE_KEY='memoryV4Queue';
const $=id=>document.getElementById(id);

async function load(){
  const cfg=Object.assign({},DEFAULTS,await chrome.storage.local.get(DEFAULTS));
  const q=(await chrome.storage.local.get({[QUEUE_KEY]:{}}))[QUEUE_KEY]||{};
  const items=Object.values(q);
  $('api').textContent=cfg.apiUrl;
  $('tenant').textContent=cfg.tenant;
  $('queue').textContent=String(items.length);
  $('error').textContent=items.find(x=>x.lastError)?.lastError||'Nenhum';
  const box=$('capture');
  if(!cfg.enabled){box.textContent='CAPTURA DESATIVADA';box.className='status warn';}
  else{box.textContent='CAPTURA ATIVA';box.className='status ok';}
  try{
    const r=await fetch(`${cfg.apiUrl}/health`,{cache:'no-store'});
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const data=await r.json();
    $('server').textContent=`${data.service||'V4'} ${data.version||''}`.trim();
  }catch(e){
    $('server').textContent='INDISPONÍVEL';
    box.textContent='CAPTURA SEM CONEXÃO COM A V4';
    box.className='status err';
  }
}

$('retry').addEventListener('click',async()=>{await chrome.runtime.sendMessage({type:'MEMORY_V4_FLUSH'});setTimeout(load,350);});
$('options').addEventListener('click',()=>chrome.runtime.openOptionsPage());
load();
