import './live-chat-pagination.css'

const PAGE_SIZE=40
const state=new WeakMap()
let scheduled=false

function messageNodes(pane){
  if(pane.closest('.tg-chat'))return [...pane.querySelectorAll(':scope > article')]
  return [...pane.querySelectorAll(':scope > article.bubble')]
}
function signature(nodes){
  if(!nodes.length)return '0'
  const first=nodes[0],last=nodes[nodes.length-1]
  return `${nodes.length}:${first.textContent?.slice(0,80)||''}:${last.textContent?.slice(0,80)||''}`
}
function updateLoader(pane,nodes,shown){
  const hidden=Math.max(0,nodes.length-shown)
  let loader=pane.querySelector(':scope > .chat-history-loader')
  if(!hidden){loader?.remove();return}
  if(!loader){loader=document.createElement('div');loader.className='chat-history-loader';pane.insertBefore(loader,pane.firstChild)}
  loader.innerHTML=`<button type="button">↑ Load earlier messages</button><span>${hidden} older message${hidden===1?'':'s'}</span>`
  loader.querySelector('button').onclick=()=>loadEarlier(pane)
}
function loadEarlier(pane){
  const nodes=messageNodes(pane)
  if(!nodes.length)return
  const previous=state.get(pane)||{shown:PAGE_SIZE,count:nodes.length,signature:signature(nodes)}
  const oldHeight=pane.scrollHeight
  const oldTop=pane.scrollTop
  const shown=Math.min(nodes.length,(previous.shown||PAGE_SIZE)+PAGE_SIZE)
  const hidden=Math.max(0,nodes.length-shown)

  // Reveal the next page directly. Do not call apply() here: Vue/live-chat DOM
  // mutations can race the click handler and previously caused the window to
  // be reset before the newly revealed messages became visible.
  nodes.forEach((node,index)=>node.classList.toggle('chat-history-hidden',index<hidden))
  state.set(pane,{shown,count:nodes.length,signature:signature(nodes)})
  updateLoader(pane,nodes,shown)
  requestAnimationFrame(()=>{pane.scrollTop=oldTop+(pane.scrollHeight-oldHeight)})
}
function apply(pane){
  const nodes=messageNodes(pane)
  if(!nodes.length){pane.querySelector(':scope > .chat-history-loader')?.remove();state.delete(pane);return}
  const sig=signature(nodes),previous=state.get(pane)
  let shown=previous?.shown||PAGE_SIZE
  // A conversation switch normally replaces the message set. Reset to the newest page.
  if(previous&&previous.signature!==sig&&nodes.length<previous.count)shown=PAGE_SIZE
  shown=Math.min(Math.max(PAGE_SIZE,shown),nodes.length)
  const hidden=Math.max(0,nodes.length-shown)
  nodes.forEach((node,index)=>node.classList.toggle('chat-history-hidden',index<hidden))
  state.set(pane,{shown,count:nodes.length,signature:sig})
  updateLoader(pane,nodes,shown)
}
function scan(){scheduled=false;document.querySelectorAll('.chat-panel .messages,.tg-chat .messages').forEach(apply)}
function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(scan)}
export function installLiveChatPagination(){
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true})
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
