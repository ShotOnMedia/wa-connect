let timer=null
let lastState=''

function activeGlobalSettingsLabel(){
  const buttons=[...document.querySelectorAll('.platform-sidebar .subnav button.active')]
  return buttons.map(b=>b.textContent.trim().toLowerCase()).find(Boolean)||''
}

function syncUsersView(){
  const app=document.querySelector('.settings-app .shell')
  if(!app)return
  const label=activeGlobalSettingsLabel()
  if(label!=='users'){lastState='';return}
  const usersButton=[...app.querySelectorAll('.nav button')].find(b=>b.textContent.trim().startsWith('Users'))
  if(!usersButton)return
  const key=`users:${usersButton.classList.contains('active')}`
  if(usersButton.classList.contains('active')){lastState=key;return}
  if(lastState===key)return
  lastState=key
  usersButton.click()
}

function schedule(){clearTimeout(timer);timer=setTimeout(syncUsersView,30)}

export function installSettingsUsersMount(){
  const observer=new MutationObserver(schedule)
  observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']})
  schedule()
  window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})
}
