import './live-chat-date-separators.css'

let scheduled=false

function timestampElement(article){
  return article.querySelector('time')||article.querySelector('footer span:first-child')
}

function rawTimestamp(article){
  const el=timestampElement(article)
  return el?.dataset?.rawTimestamp||el?.getAttribute?.('datetime')||''
}

function dateValue(raw){
  if(!raw)return null
  const date=new Date(raw)
  return Number.isNaN(date.getTime())?null:date
}

function dayKey(raw){
  const date=dateValue(raw)
  if(!date)return ''
  const parts=new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date)
  const values=Object.fromEntries(parts.map(part=>[part.type,part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function longDate(raw){
  const date=dateValue(raw)
  if(!date)return ''
  return new Intl.DateTimeFormat(undefined,{day:'numeric',month:'long',year:'numeric'}).format(date)
}

function makeVisual(label){
  const visual=document.createElement('div')
  visual.className='live-chat-date-separator-visual'
  visual.setAttribute('aria-hidden','true')

  const before=document.createElement('span')
  before.className='live-chat-date-line'
  const text=document.createElement('span')
  text.className='live-chat-date-label'
  text.textContent=label
  const after=document.createElement('span')
  after.className='live-chat-date-line'
  visual.append(before,text,after)
  return visual
}

function renderPane(pane){
  pane.querySelectorAll(':scope > .live-chat-date-separator-visual').forEach(el=>el.remove())

  const articles=[...pane.querySelectorAll(':scope > article')]
  if(!articles.length)return

  // The compact date renderer still creates its own in-bubble markers. Hide
  // those, but do not depend on them: pagination and async timestamp hydration
  // can recreate/remove them in a different order on WhatsApp and Telegram.
  articles.forEach(article=>{
    article.querySelectorAll(':scope > .live-chat-date-separator').forEach(source=>{
      source.classList.add('live-chat-date-separator-source')
    })
  })

  const visible=articles.filter(article=>!article.classList.contains('chat-history-hidden'))
  let previousDay=''
  visible.forEach(article=>{
    const raw=rawTimestamp(article)
    const key=dayKey(raw)
    if(!key)return
    if(key!==previousDay){
      const label=longDate(raw)
      if(label)pane.insertBefore(makeVisual(label),article)
    }
    previousDay=key
  })
}

function scan(){
  scheduled=false
  document.querySelectorAll('.chat-panel .messages,.tg-chat .messages,.telegram-page .messages').forEach(renderPane)
}

function schedule(){
  if(scheduled)return
  scheduled=true
  requestAnimationFrame(scan)
}

export function installLiveChatDateSeparators(){
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','datetime','data-raw-timestamp']})
  window.addEventListener('wa-connect-timezone-change',schedule)
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
