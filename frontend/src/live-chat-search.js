const BASE=(import.meta.env.VITE_API_BASE_URL||'/api/v1').replace(/\/$/,'')
const state={whatsapp:'',telegram:''}
let timer=null,busy=false

async function search(channel,q){
  const r=await fetch(`${BASE}/live-chat-search/${channel}?q=${encodeURIComponent(q)}`,{credentials:'include'})
  if(!r.ok)throw new Error(`Search failed (${r.status})`)
  return r.json()
}

function whatsappHost(){
  const list=document.querySelector('.conversation-list')
  if(!list)return null
  return list.querySelector('.filters')||list.querySelector('.assignment-filters')||list.querySelector('header')
}
function rows(channel){return [...document.querySelectorAll('.conversation-list > .conversation-row')]}
function normalize(v){return String(v??'').trim()}
function rowIdentity(row,channel){return normalize(row.querySelector('.row-top strong')?.textContent)}
function resultIdentity(item,channel){return normalize(item.contact?.name||item.contact?.wa_id)}
function restore(channel){rows(channel).forEach(r=>r.style.removeProperty('display'));document.querySelector(`.live-chat-search-empty[data-channel="${channel}"]`)?.remove()}
function apply(channel,results){
  const list=document.querySelector('.conversation-list')
  if(!list)return
  const ids=new Set(results.map(r=>String(r.id)))
  const names=new Set(results.map(r=>resultIdentity(r,channel)))
  let shown=0
  rows(channel).forEach(r=>{
    const match=names.has(rowIdentity(r,channel))
    r.style.display=match?'':'none';if(match)shown++
  })
  list.querySelector(`.live-chat-search-empty[data-channel="${channel}"]`)?.remove()
  if(!shown){const e=document.createElement('div');e.className='live-chat-search-empty';e.dataset.channel=channel;e.textContent=ids.size?'Matching conversation is not currently rendered. Refresh the inbox.':'No matching conversations.';list.appendChild(e)}
}
async function run(channel,input){
  const q=input.value.trim();state[channel]=q;input.parentElement?.classList.toggle('has-value',!!q)
  if(!q){restore(channel);return}
  try{busy=true;input.classList.add('searching');apply(channel,await search(channel,q))}catch(e){console.warn('[live-chat-search]',e)}finally{busy=false;input.classList.remove('searching')}
}
function mount(channel,host){
  const list=document.querySelector('.conversation-list')
  if(!list||list.querySelector(`.live-chat-search[data-channel="${channel}"]`))return
  const wrap=document.createElement('div');wrap.className='live-chat-search';wrap.dataset.channel=channel
  wrap.innerHTML='<span class="live-chat-search-icon">⌕</span><input type="search" autocomplete="off" placeholder="Search conversations…" aria-label="Search conversations"><button type="button" title="Clear search">×</button>'
  const input=wrap.querySelector('input'),clear=wrap.querySelector('button');input.value=state[channel]
  input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>run(channel,input),275)})
  clear.addEventListener('click',()=>{input.value='';state[channel]='';run(channel,input);input.focus()})
  host.insertAdjacentElement('afterend',wrap)
  if(input.value)run(channel,input)
}
function ensure(){
  const wh=whatsappHost();if(wh)mount('whatsapp',wh)
  const channel='whatsapp';if(state[channel]){const input=document.querySelector(`.live-chat-search[data-channel="${channel}"] input`);if(input&&!busy)run(channel,input)}
}
export function installLiveChatSearch(){
  let queued=false
  const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;ensure()})}
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true})
  schedule()
}
