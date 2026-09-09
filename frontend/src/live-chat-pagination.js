import './live-chat-pagination.css'

const PAGE_SIZE=40
const state=new WeakMap()
let scheduled=false

function messageNodes(pane){
  if(pane.closest('.tg-chat'))return [...pane.querySelectorAll(':scope > article')]
  return [...pane.querySelectorAll(':scope > article.bubble')]
}
function conversationKey(pane){
  const tg=pane.closest('.tg-chat')
  if(tg){const active=tg.querySelector('.tg-list .row.active');return `tg:${active?.textContent||''}`}
  const app=pane.closest('.app-shell,.workspace-shell')||document
  const active=app.querySelector('.conversation-list .active,.inbox-list .active,.conversation-row.active')
  return `wa:${active?.textContent||''}`
}
function preserveScroll(pane,fn){const oldHeight=pane.scrollHeight,oldTop=pane.scrollTop;fn();requestAnimationFrame(()=>{pane.scrollTop=oldTop+(pane.scrollHeight-oldHeight)})}
function apply(pane){
  const nodes=messageNodes(pane)
  if(!nodes.length){pane.querySelector(':scope > .chat-history-loader')?.remove();state.delete(pane);return}
  const key=conversationKey(pane),previous=state.get(pane)
  let shown=previous?.key===key?(previous.shown||PAGE_SIZE):PAGE_SIZE
  shown=Math.min(Math.max(PAGE_SIZE,shown),nodes.length)
  const hidden=Math.max(0,nodes.length-shown)
  nodes.forEach((node,index)=>node.classList.toggle('chat-history-hidden',index<hidden))
  state.set(pane,{shown,count:nodes.length,key})
  let loader=pane.querySelector(':scope > .chat-history-loader')
  if(!hidden){loader?.remove();return}
  if(!loader){loader=document.createElement('div');loader.className='chat-history-loader';pane.insertBefore(loader,pane.firstChild)}
  loader.innerHTML=`<button type="button">↑ Load earlier messages</button><span>${hidden} older message${hidden===1?'':'s'}</span>`
  loader.querySelector('button').onclick=()=>{
    const current=state.get(pane)||{shown:PAGE_SIZE,key}
    const nextShown=Math.min(nodes.length,current.shown+PAGE_SIZE)
    // Unhide directly before the observer gets another chance to scan. This makes
    // the click visible immediately even in chats whose Vue tree is polling.
    const nextHidden=Math.max(0,nodes.length-nextShown)
    preserveScroll(pane,()=>{
      nodes.forEach((node,index)=>node.classList.toggle('chat-history-hidden',index<nextHidden))
      current.shown=nextShown;current.count=nodes.length;current.key=key;state.set(pane,current)
      if(nextHidden){loader.querySelector('span').textContent=`${nextHidden} older message${nextHidden===1?'':'s'}`}
      else loader.remove()
    })
  }
}
function scan(){scheduled=false;document.querySelectorAll('.chat-panel .messages,.tg-chat .messages').forEach(apply)}
function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(scan)}
export function installLiveChatPagination(){
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true})
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
