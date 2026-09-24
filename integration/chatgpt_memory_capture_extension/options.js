const DEFAULTS={apiUrl:'http://127.0.0.1:8787',tenant:'LEGACY',clientId:'chatgpt-capture',clientSecret:'',enabled:true};
function consumePairingFragment(){
  const p=new URLSearchParams(location.hash.replace(/^#/,''));
  const clientId=p.get('client_id'), secret=p.get('secret');
  if(clientId&&secret){
    chrome.storage.local.set({clientId,clientSecret:secret}).then(()=>history.replaceState(null,'',location.pathname));
  }
}
async function load(){
  consumePairingFragment();
  const v=Object.assign({},DEFAULTS,await chrome.storage.local.get(DEFAULTS));
  apiUrl.value=v.apiUrl; tenant.value=v.tenant; clientId.value=v.clientId; clientSecret.value=v.clientSecret; enabled.checked=v.enabled;
}
save.addEventListener('click',async()=>{
  await chrome.storage.local.set({apiUrl:apiUrl.value.trim(),tenant:tenant.value.trim().toUpperCase(),clientId:clientId.value.trim(),clientSecret:clientSecret.value.trim(),enabled:enabled.checked});
  status.textContent=' Salvo'; setTimeout(()=>status.textContent='',1500);
});
load();
