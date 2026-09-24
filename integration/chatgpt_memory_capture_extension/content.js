const state = new WeakMap();
let scanTimer = null;

function conversationRef() {
  const path = location.pathname;
  let m = path.match(/\/g\/g-p-([^/]+)\/c\/([^/?#]+)/);
  if (m) return {external_session_ref: path, project_id: m[1], conversation_id: m[2]};
  m = path.match(/\/c\/([^/?#]+)/);
  if (m) return {external_session_ref: path, project_id: null, conversation_id: m[1]};
  return null;
}

async function sha256(text) {
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2,'0')).join('');
}

function sourceMessageId(node, index, role, text) {
  const holder = node.closest('[data-message-id]') || node.querySelector('[data-message-id]');
  const raw = holder?.getAttribute('data-message-id') || node.getAttribute('data-message-id') || node.id || '';
  if (raw) return Promise.resolve(raw);
  return sha256(`${role}|${index}|${text}`).then(h => `dom-${index}-${h.slice(0,24)}`);
}

async function scanStableMessages() {
  const ref = conversationRef();
  if (!ref) return;
  const nodes = [...document.querySelectorAll('[data-message-author-role]')];
  const now = Date.now();
  for (let index=0; index<nodes.length; index++) {
    const node = nodes[index];
    const role = (node.getAttribute('data-message-author-role') || '').trim().toLowerCase();
    const text = (node.innerText || node.textContent || '').trim();
    if (!role || !text) continue;
    const prev = state.get(node);
    if (!prev || prev.text !== text) {
      state.set(node, {text, stableSince: now, queued: false});
      continue;
    }
    if (prev.queued || now - prev.stableSince < 3500) continue;
    const message_id = await sourceMessageId(node, index, role, text);
    const payload = {
      provider: 'chatgpt',
      external_session_ref: ref.external_session_ref,
      objective: (document.title || 'ChatGPT conversation').slice(0,10000),
      role,
      text,
      message_id,
      ordinal: index,
      project_id: ref.project_id,
      capture_source: 'CHATGPT_AUTHORIZED_EXTENSION',
      process_now: true
    };
    try {
      const response = await chrome.runtime.sendMessage({type:'MEMORY_V4_TURN', payload});
      if (response?.queued) {
        prev.queued = true;
        state.set(node, prev);
      }
    } catch (_) {
      // background queue will be retried by the next scan/startup
    }
  }
}

function scheduleScan() {
  if (scanTimer) clearTimeout(scanTimer);
  scanTimer = setTimeout(() => scanStableMessages().catch(() => {}), 4000);
}

new MutationObserver(scheduleScan).observe(document.documentElement, {subtree:true, childList:true, characterData:true});
window.addEventListener('popstate', scheduleScan);
setInterval(() => scanStableMessages().catch(() => {}), 15000);
scheduleScan();
