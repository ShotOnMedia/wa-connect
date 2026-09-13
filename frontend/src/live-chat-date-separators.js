import './live-chat-date-separators.css'

let scheduled=false

function cloneSeparator(source){
  const visual=document.createElement('div')
  visual.className='live-chat-date-separator-visual'
  visual.setAttribute('aria-hidden','true')
  visual.innerHTML=source.innerHTML
  return visual
}

function timestampElement(article){
  return article.querySelector('time')||article.querySelector('footer span:first-child')
}

function rawTimestamp(article){
  const el=timestampElement(article)
  return el?.dataset?.rawTimestamp||el?.getAttribute?.('datetime')||''
}

function dayKey(raw){
  if(!raw)return ''
  const date=new Date(raw)
  if(Number.isNaN(date.getTime()))return ''
  const parts=new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date)
  const values=Object.fromEntries(parts.map(part=>[part.type,part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function renderPane(pane){
  pane.querySelectorAll(':scope > .live-chat-date-separator-visual').forEach(el=>el.remove())
  const articles=[...pane.querySelectorAll(':scope > article')]
  if(!articles.length)return

  // Keep the original generated separators as the source of truth for the
  // configured timezone/date label, but render them as full-width pane rows.
  // Pagination can hide the first article of a day, so index every day's source
  // before deciding which visible article should receive the separator.
  const sourcesByDay=new Map()
  articles.forEach(article=>{
    const source=article.querySelector(':scope > .live-chat-date-separator')
    if(source){
      source.classList.add('live-chat-date-separator-source')
      const key=dayKey(rawTimestamp(article))
      if(key&&!sourcesByDay.has(key))sourcesByDay.set(key,source)
    }
  })

  const visible=articles.filter(article=>!article.classList.contains('chat-history-hidden'))
  let previousDay=''
  visible.forEach(article=>{
    const key=dayKey(rawTimestamp(article))
    if(!key||key===previousDay)return
    const source=sourcesByDay.get(key)||article.querySelector(':scope > .live-chat-date-separator')
    if(source)pane.insertBefore(cloneSeparator(source),article)
    previousDay=key
  })
}

function scan(){
  scheduled=false
  document.querySelectorAll('.chat-panel .messages,.tg-chat .messages').forEach(renderPane)
}

function schedule(){
  if(scheduled)return
  scheduled=true
  requestAnimationFrame(scan)
}

export function installLiveChatDateSeparators(){
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']})
  window.addEventListener('wa-connect-timezone-change',schedule)
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
