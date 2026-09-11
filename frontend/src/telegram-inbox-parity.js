import { api } from './api'
import './telegram-inbox-parity.css'

let busy=false
let lastConversationId=null

function esc(v=''){return String(v).replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]))}

async function currentConversation(root){
  const active=root.querySelector('.tg-list .row.active')
  if(!active)return null
  const rows=[...root.querySelectorAll('.tg-list .row')]
  const index=rows.indexOf(active)
  const conversations=await api.telegramConversations().catch(()=>[])
  return conversations[index]||null
}

async function assign(conversationId,userId){
  const response=await fetch(`/api/v1/telegram/conversations/${conversationId}/assignment`,{
    method:'PATCH',credentials:'include',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id:userId?Number(userId):null})
  })
  if(!response.ok){const p=await response.json().catch(()=>({}));throw new Error(p.detail||`Assignment failed (${response.status})`)}
  return response.json()
}

async function decorate(){
  if(busy)return
  const root=document.querySelector('.tg-chat')
  if(!root)return
  busy=true
  try{
    const [me,agents,conversation]=await Promise.all([api.me(),api.agents().catch(()=>[]),currentConversation(root)])
    if(!conversation)return
    const header=root.querySelector('.chat > header .header-actions')
    if(!header)return
    let box=header.querySelector('.tg-assignment-control')
    if(!box){box=document.createElement('div');box.className='tg-assignment-control';header.prepend(box)}
    const canAssign=['admin','manager'].includes(me.role)
    if(canAssign){
      const options=[`<option value="">Unassigned</option>`,...agents.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`)].join('')
      box.innerHTML=`<select aria-label="Assign Telegram conversation">${options}</select>`
      const select=box.querySelector('select');select.value=String(conversation.assigned_user_id||'')
      select.onchange=async()=>{select.disabled=true;try{await assign(conversation.id,select.value||null);lastConversationId=null;await decorate()}catch(e){alert(e.message)}finally{select.disabled=false}}
    }else if(!conversation.assigned_user_id){
      box.innerHTML='<button type="button" class="tg-take">Take conversation</button>'
      box.querySelector('button').onclick=async()=>{try{await assign(conversation.id,me.id);lastConversationId=null;await decorate()}catch(e){alert(e.message)}}
    }else box.innerHTML='<span class="tg-assigned">Assigned to you</span>'

    const panel=root.querySelector('.customer-panel .snapshot')
    if(panel){
      panel.querySelector('.tg-assigned-row')?.remove()
      const row=document.createElement('div');row.className='tg-assigned-row'
      const agent=agents.find(a=>Number(a.id)===Number(conversation.assigned_user_id))
      row.innerHTML=`<dt>Assigned to</dt><dd>${esc(agent?.name|| (conversation.assigned_user_id?'Assigned':'Unassigned'))}</dd>`
      panel.prepend(row)
    }
    lastConversationId=conversation.id
  } finally {busy=false}
}

export function installTelegramInboxParity(){
  let timer
  const schedule=()=>{clearTimeout(timer);timer=setTimeout(()=>decorate().catch(()=>{}),80)}
  new MutationObserver(schedule).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']})
  schedule()
  window.setInterval(()=>decorate().catch(()=>{}),3000)
}
