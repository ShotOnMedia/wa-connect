import { api } from './api'

let timer=null
let running=false

function rawTimestamp(message){
  return message?.telegram_timestamp||message?.created_at||message?.timestamp||message?.sent_at||message?.received_at||''
}

function telegramIdFromHeader(){
  const text=document.querySelector('.tg-chat .chat header .identity span')?.textContent||''
  const match=text.match(/@(\d+)/)
  return match?.[1]||''
}

async function stamp(){
  if(running)return
  const pane=document.querySelector('.tg-chat .messages')
  const telegramId=telegramIdFromHeader()
  if(!pane||!telegramId)return

  running=true
  try{
    const conversations=await api.telegramConversations().catch(()=>[])
    const conversation=(conversations||[]).find(c=>String(c?.contact?.telegram_user_id||'')===String(telegramId))
    if(!conversation?.id)return

    const messages=await api.telegramMessages(conversation.id).catch(()=>[])
    const articles=[...pane.querySelectorAll(':scope > article')]
    if(!articles.length||!messages.length)return

    // The Vue chat renders the API message array in the same order. Align from
    // the end as a safeguard if presentation paging temporarily hides/removes
    // older rows while the conversation is being refreshed.
    const offset=Math.max(0,messages.length-articles.length)
    let changed=false
    articles.forEach((article,index)=>{
      const message=messages[offset+index]
      const time=article.querySelector('time')||article.querySelector('footer span:first-child')
      const raw=rawTimestamp(message)
      if(!time||!raw)return
      if(time.dataset.rawTimestamp!==raw){
        time.dataset.rawTimestamp=raw
        changed=true
      }
      if(time.tagName==='TIME'&&time.getAttribute('datetime')!==raw){
        time.setAttribute('datetime',raw)
        changed=true
      }
    })

    if(changed)window.dispatchEvent(new Event('wa-connect-timezone-change'))
  }finally{
    running=false
  }
}

function schedule(){
  clearTimeout(timer)
  timer=setTimeout(()=>stamp().catch(()=>{}),80)
}

export function installTelegramMessageTimestamps(){
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true,characterData:true})
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
