let observer=null
let modal=null

function esc(value=''){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function apiBase(){return '/api/v1'}
async function request(path,options={}){
  const response=await fetch(`${apiBase()}${path}`,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options})
  const data=await response.json().catch(()=>null)
  if(!response.ok)throw new Error(data?.detail||`Request failed (${response.status})`)
  return data
}
function closeModal(){modal?.remove();modal=null}
function showEditor(row){
  const name=row.querySelector('.user-copy strong')?.textContent.trim()||''
  const email=row.querySelector('.user-copy span')?.textContent.trim()||''
  const id=row.dataset.userId
  if(!id)return
  closeModal()
  modal=document.createElement('div');modal.className='user-edit-overlay'
  modal.innerHTML=`<div class="user-edit-modal"><div class="user-edit-head"><div><p class="eyebrow">Team member</p><h2>Edit user</h2></div><button type="button" class="user-edit-close" aria-label="Close">×</button></div><form><label>Name<input name="name" value="${esc(name)}" minlength="2" maxlength="150" required></label><label>Email<input value="${esc(email)}" disabled><small>Email/login cannot currently be changed.</small></label><label>New password<input name="password" type="password" minlength="8" maxlength="512" autocomplete="new-password" placeholder="Leave blank to keep current password"><small>At least 8 characters.</small></label><label>Confirm new password<input name="confirm" type="password" minlength="8" maxlength="512" autocomplete="new-password" placeholder="Repeat new password"></label><p class="user-edit-error" hidden></p><div class="user-edit-actions"><button type="button" class="secondary user-edit-cancel">Cancel</button><button type="submit" class="primary">Save changes</button></div></form></div>`
  document.body.appendChild(modal)
  modal.querySelector('.user-edit-close').onclick=closeModal;modal.querySelector('.user-edit-cancel').onclick=closeModal
  modal.addEventListener('click',e=>{if(e.target===modal)closeModal()})
  modal.querySelector('form').onsubmit=async e=>{
    e.preventDefault();const form=e.currentTarget,err=form.querySelector('.user-edit-error'),save=form.querySelector('[type=submit]')
    const newName=form.elements.name.value.trim(),password=form.elements.password.value,confirm=form.elements.confirm.value
    err.hidden=true
    if(password!==confirm){err.textContent='The new passwords do not match.';err.hidden=false;return}
    const payload={name:newName};if(password)payload.password=password
    save.disabled=true;save.textContent='Saving…'
    try{
      const updated=await request(`/users/${id}`,{method:'PATCH',body:JSON.stringify(payload)})
      row.querySelector('.user-copy strong').textContent=updated.name
      closeModal()
    }catch(ex){err.textContent=ex.message;err.hidden=false;save.disabled=false;save.textContent='Save changes'}
  }
}
function enhance(){
  document.querySelectorAll('.settings-app .user-row').forEach(row=>{
    if(row.dataset.detailsEditor)return
    const buttons=[...row.querySelectorAll('button')],status=row.querySelector('.status-pill'),copy=row.querySelector('.user-copy')
    const toggle=buttons.find(b=>/^(deactivate|activate)$/i.test(b.textContent.trim()))
    const role=row.querySelector('select')
    if(!toggle||!role||!copy)return
    const allRows=[...document.querySelectorAll('.settings-app .user-row')]
    const index=allRows.indexOf(row)
    const usersRequest=performance.getEntriesByType('resource').map(x=>x.name).find(x=>/\/api\/v1\/users(?:\?|$)/.test(x))
    // App.vue renders users in API order. Keep a stable local marker and resolve the real id below when clicked.
    row.dataset.detailsEditor='1';row.dataset.userIndex=String(index)
    const edit=document.createElement('button');edit.type='button';edit.className='secondary user-edit-button';edit.textContent='Edit details';toggle.before(edit)
    edit.onclick=async()=>{
      try{const users=await request('/users');const user=users[Number(row.dataset.userIndex)];if(!user)throw new Error('User could not be resolved');row.dataset.userId=String(user.id);showEditor(row)}catch(ex){window.alert(ex.message)}
    }
  })
}
export function installUserDetailsEditor(){
  observer=new MutationObserver(()=>requestAnimationFrame(enhance));observer.observe(document.body,{childList:true,subtree:true});enhance()
  window.addEventListener('beforeunload',()=>observer?.disconnect(),{once:true})
}
