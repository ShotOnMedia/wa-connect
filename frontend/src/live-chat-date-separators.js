import './live-chat-date-separators.css'

let scheduled=false

function cloneSeparator(source){
  const visual=document.createElement('div')
  visual.className='live-chat-date-separator-visual'
  visual.setAttribute('aria-hidden','true')
  visual.innerHTML=source.innerHTML
  return visual
}

function renderPane(pane){
  // The display helper attaches its separator to the message article. Message
  // articles have different widths/alignment in WhatsApp and Telegram, so a
  // separator positioned inside them can never be reliably centred in the
  // whole chat. Mirror it as a direct pane child instead.
  pane.querySelectorAll(':scope > .live-chat-date-separator-visual').forEach(el=>el.remove())
  const articles=[...pane.querySelectorAll(':scope > article')]
  articles.forEach(article=>{
    const source=article.querySelector(':scope > .live-chat-date-separator')
    if(!source)return
    source.classList.add('live-chat-date-separator-source')
    const visual=cloneSeparator(source)
    pane.insertBefore(visual,article)
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
  observer.observe(document.body,{subtree:true,childList:true,characterData:true})
  window.addEventListener('wa-connect-timezone-change',schedule)
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
