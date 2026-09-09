import './live-chat-pagination.css'

const PAGE_SIZE=40
let scheduled=false

function messageNodes(pane){
  if(pane.closest('.tg-chat'))return [...pane.querySelectorAll(':scope > article')]
  return [...pane.querySelectorAll(':scope > article.bubble')]
}
function currentShown(pane,total){
  const saved=Number.parseInt(pane.dataset.chatHistoryShown||'',10)
  return Number.isFinite(saved)?Math.min(Math.max(PAGE_SIZE,saved),total):Math.min(PAGE_SIZE,total)
}
function preserveScroll(pane,fn){
  const oldHeight=pane.scrollHeight,oldTop=pane.scrollTop
  fn()
  requestAnimationFrame(()=>{pane.scrollTop=oldTop+(pane.scrollHeight-oldHeight)})
}
function render(pane){
  const nodes=messageNodes(pane)
  if(!nodes.length){pane.querySelector(':scope > .chat-history-loader')?.remove();return}
  const shown=currentShown(pane,nodes.length),hidden=Math.max(0,nodes.length-shown)
  pane.dataset.chatHistoryShown=String(shown)
  nodes.forEach((node,index)=>node.classList.toggle('chat-history-hidden',index<hidden))
  let loader=pane.querySelector(':scope > .chat-history-loader')
  if(!hidden){loader?.remove();return}
  if(!loader){
    loader=document.createElement('div')
    loader.className='chat-history-loader'
    loader.innerHTML='<button type="button">↑ Load earlier messages</button><span></span>'
    pane.insertBefore(loader,pane.firstChild)
  }
  loader.querySelector('span').textContent=`${hidden} older message${hidden===1?'':'s'}`
}
function loadEarlier(button){
  const pane=button.closest('.messages')
  if(!pane)return
  const nodes=messageNodes(pane)
  const shown=currentShown(pane,nodes.length)
  pane.dataset.chatHistoryShown=String(Math.min(nodes.length,shown+PAGE_SIZE))
  preserveScroll(pane,()=>render(pane))
}
function scan(){scheduled=false;document.querySelectorAll('.chat-panel .messages,.tg-chat .messages').forEach(render)}
function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(scan)}
export function installLiveChatPagination(){
  // Delegate the click from document so Vue polling/re-rendering cannot orphan a
  // handler attached to a loader element that has just been replaced.
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('.chat-history-loader button')
    if(!button)return
    event.preventDefault();event.stopPropagation();loadEarlier(button)
  })
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true})
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
