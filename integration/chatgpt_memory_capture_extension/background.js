const DEFAULTS = {
  apiUrl: "https://desktop-jns08pu.tail7ad8aa.ts.net:8788",
  tenant: "LEGACY",
  clientId: "chatgpt-capture",
  clientSecret: "",
  enabled: true
};
const QUEUE_KEY = "memoryV4Queue";

async function settings() {
  return Object.assign({}, DEFAULTS, await chrome.storage.local.get(DEFAULTS));
}

async function queueGet() {
  const data = await chrome.storage.local.get({ [QUEUE_KEY]: {} });
  return data[QUEUE_KEY] || {};
}

async function queueSet(queue) {
  await chrome.storage.local.set({ [QUEUE_KEY]: queue });
}

function eventKey(payload) {
  return `${payload.provider}|${payload.external_session_ref}|${payload.message_id}`;
}

function b64urlToBytes(value){
  const padded=value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4);
  const raw=atob(padded);
  return Uint8Array.from(raw,c=>c.charCodeAt(0));
}

async function sha256Hex(bytes){
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
}

async function signedHeaders(cfg, method, pathQuery, bodyText){
  if(!cfg.clientId || !cfg.clientSecret) throw new Error('AUTH_NOT_CONFIGURED');
  const enc=new TextEncoder();
  const bodyBytes=enc.encode(bodyText||'');
  const bodyHash=await sha256Hex(bodyBytes);
  const timestamp=Math.floor(Date.now()/1000).toString();
  const nonceBytes=crypto.getRandomValues(new Uint8Array(16));
  const nonce=[...nonceBytes].map(b=>b.toString(16).padStart(2,'0')).join('');
  const canonical=`${method.toUpperCase()}\n${pathQuery}\n${timestamp}\n${nonce}\n${bodyHash}`;
  const key=await crypto.subtle.importKey('raw',b64urlToBytes(cfg.clientSecret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const sig=await crypto.subtle.sign('HMAC',key,enc.encode(canonical));
  const signature=[...new Uint8Array(sig)].map(b=>b.toString(16).padStart(2,'0')).join('');
  return {
    'X-Memory-Client-Id':cfg.clientId,
    'X-Memory-Timestamp':timestamp,
    'X-Memory-Nonce':nonce,
    'X-Memory-Content-SHA256':bodyHash,
    'X-Memory-Signature':signature
  };
}

async function enqueue(payload) {
  const queue = await queueGet();
  const key = eventKey(payload);
  if (!queue[key]) queue[key] = { payload, attempts: 0, nextAttemptAt: 0, lastError: null };
  await queueSet(queue);
  await flushQueue();
  return { queued: true, key };
}

async function flushQueue() {
  const cfg = await settings();
  if (!cfg.enabled) return { processed: 0, remaining: Object.keys(await queueGet()).length };
  if (!cfg.clientSecret) {
    await chrome.storage.local.set({memoryV4LastError:'AUTH_NOT_CONFIGURED'});
    return { processed: 0, remaining: Object.keys(await queueGet()).length, auth: false };
  }

  const queue = await queueGet();
  let changed = false;
  let processed = 0;
  const path='/v1/conversation-ingestion/turn';

  for (const [key, item] of Object.entries(queue)) {
    if ((item.nextAttemptAt || 0) > Date.now()) continue;
    const bodyText=JSON.stringify(item.payload);
    const headers = Object.assign({
      'Content-Type':'application/json',
      'X-Memory-Tenant':cfg.tenant
    }, await signedHeaders(cfg,'POST',path,bodyText));
    if(item.payload.project_id) headers['X-Memory-Project']=item.payload.project_id;

    try {
      const response = await fetch(`${cfg.apiUrl}${path}`, {
        method: 'POST', headers, body: bodyText, cache: 'no-store'
      });
      if (response.ok) {
        delete queue[key]; changed = true; processed += 1;
        await chrome.storage.local.set({memoryV4LastSuccessAt:Date.now(),memoryV4LastError:null});
        continue;
      }
      const body = await response.text();
      item.attempts = (item.attempts || 0) + 1;
      item.lastError = `HTTP ${response.status}: ${body.slice(0,300)}`;
    } catch (error) {
      item.attempts = (item.attempts || 0) + 1;
      item.lastError = `${error?.name || 'Error'}: ${String(error?.message || error).slice(0,300)}`;
    }

    await chrome.storage.local.set({memoryV4LastError:item.lastError});
    item.nextAttemptAt = Date.now() + Math.min(300000, 2000 * Math.pow(2, Math.min(item.attempts,7)));
    queue[key] = item; changed = true;
  }
  if (changed) await queueSet(queue);
  return { processed, remaining:Object.keys(queue).length, auth:true };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'MEMORY_V4_TURN') { enqueue(message.payload).then(sendResponse).catch(error=>sendResponse({queued:false,error:String(error)})); return true; }
  if (message?.type === 'MEMORY_V4_FLUSH') { flushQueue().then(sendResponse).catch(error=>sendResponse({processed:0,error:String(error)})); return true; }
});

async function ensureAlarm(){ await chrome.alarms.create('memory-v4-flush',{periodInMinutes:1}); }
chrome.runtime.onInstalled.addListener(ensureAlarm);
chrome.runtime.onStartup.addListener(ensureAlarm);
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='memory-v4-flush')flushQueue();});
ensureAlarm().catch(()=>{});
flushQueue().catch(()=>{});
