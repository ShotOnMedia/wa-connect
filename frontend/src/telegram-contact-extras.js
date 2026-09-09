import { api } from './api'
import './telegram-contact-extras.css'

let signature=''
function esc(v=''){return String(v).replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]))}
function fmtPhone(v=''){const raw=String(v).trim();if(!raw)return'';const digits=raw.replace(/\D/g,'');if(digits.startsWith('27')&&digits.length===11)return `+27 ${digits.slice(2,4)} ${digits.slice(4,7)} ${digits.slice(7)}`;return raw.startsWith('+')?raw:`+${digits}`}
function card(c){const name=c?.name||[c?.first_name,c?.last_name].filter(Boolean).join(' ')||'Shared contact',phone=fmtPhone(c?.phone_number),uid=c?.user_id;return `<div class="tg-shared-contact"><div class="tg-contact-avatar">${esc(name.slice(0,1).toUpperCase())}</div><div class="tg-contact-copy"><small>Shared contact</small><strong>${esc(name)}</strong>${phone?`<a href="tel:${esc(phone)}">${esc(phone)}</a>`:''}${uid?`<span>Telegram ID: ${esc(uid)}</span>`:''}</div></div>`}
async function decorate(){
  const root=document.querySelector('.tg-chat');if(!root)return
  const selectedRow=root.querySelector('.tg-list .row.active');if(!selectedRow)return
  const rows=[...root.querySelectorAll('.tg-list .row')],index=rows.indexOf(selectedRow)
  const conversations=await api.telegramConversations().catch(()=>[]),conversation=conversations[index];if(!conversation)return
  const messages=await api.telegramMessages(conversation.id).catch(()=>[]),articles=[...root.querySelectorAll('.messages article')]
  if(messages.length!==articles.length)return
  const next=`${conversation.id}:${messages.map(m=>`${m.id}:${JSON.stringify(m.shared_contact||null)}`).join('|')}`;if(next===signature)return;signature=next
  messages.forEach((m,i)=>{const article=articles[i],bubble=article?.querySelector(':scope > div');if(!bubble)return;bubble.querySelector('.tg-shared-contact')?.remove();if(m.message_type!=='contact'||!m.shared_contact)return;const p=bubble.querySelector('p');if(p)p.style.display='none';const box=document.createElement('div');box.innerHTML=card(m.shared_contact);const time=bubble.querySelector('time');bubble.insertBefore(box.firstElementChild,time||null)})
}
export function installTelegramContactExtras(){let timer;const schedule=()=>{clearTimeout(timer);timer=setTimeout(()=>decorate().catch(()=>{}),100)};new MutationObserver(schedule).observe(document.body,{subtree:true,childList:true,characterData:true});schedule()}
