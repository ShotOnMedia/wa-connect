import { api } from './api'

let isAgent=false
let timer=null

function applyAgentChatUi(){
  if(!isAgent)return
  const filters=document.querySelector('.channel-app .assignment-filters')
  if(!filters)return
  const buttons=[...filters.querySelectorAll('button')]
  for(const button of buttons){
    const label=button.textContent.trim().toLowerCase()
    if(label==='all'){
      button.textContent='Assigned to me'
      button.style.display=''
    }else{
      button.style.display='none'
    }
  }
}

function schedule(){clearTimeout(timer);timer=setTimeout(applyAgentChatUi,50)}

export async function installAgentChatVisibility(){
  try{isAgent=(await api.me())?.role==='agent'}catch(_){return}
  if(!isAgent)return
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true})
  applyAgentChatUi()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
