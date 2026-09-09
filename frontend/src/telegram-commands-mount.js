import {createApp} from 'vue'
import TelegramCommands from './TelegramCommands.vue'

let mounted=null
function scan(){
  const settings=document.querySelector('.tg-settings')
  if(!settings){mounted=null;return}
  if(settings.querySelector('.telegram-commands-mount'))return
  const host=document.createElement('div')
  host.className='telegram-commands-mount'
  host.style.marginTop='18px'
  settings.appendChild(host)
  createApp(TelegramCommands).mount(host)
  mounted=host
}
export function installTelegramCommands(){
  let pending=false
  const schedule=()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;scan()})}
  new MutationObserver(schedule).observe(document.body,{subtree:true,childList:true})
  schedule()
}
