import { api } from './api'
import './flow-trigger-extras.css'

let busy=false
function phrases(value){
  const raw=String(value||'').trim()
  let items=[]
  if(raw.startsWith('[')){
    try{const parsed=JSON.parse(raw);if(Array.isArray(parsed))items=parsed}catch(_){}
  }
  if(!items.length&&raw)items=raw.split(/\r?\n/)
  const seen=new Set()
  return items.map(v=>String(v).trim()).filter(v=>{const k=v.toLowerCase();if(!v||seen.has(k))return false;seen.add(k);return true})
}
function encodePhrases(values){return JSON.stringify(values)}
function dispatchValue(input,value){const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;setter?.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))}
function currentFlowId(drawer){const root=drawer.closest('.vfb');return Number(root?.querySelector('.toolbar select')?.value||0)}
async function duplicateOwner(drawer,phrase){const flowId=currentFlowId(drawer),needle=phrase.trim().toLowerCase();if(!needle)return null;try{const rows=await api.flows('active');return rows.find(f=>Number(f.id)!==flowId&&f.trigger_type==='keyword'&&phrases(f.trigger_value).some(p=>p.toLowerCase()===needle))||null}catch(_){return null}}
function render(editor,input){const values=phrases(input.value),chips=editor.querySelector('.trigger-chips');chips.innerHTML=values.map((v,i)=>`<span>${escapeHtml(v)}<button type="button" data-index="${i}" title="Remove trigger">×</button></span>`).join('');editor.querySelector('.trigger-empty').hidden=values.length>0;chips.querySelectorAll('button').forEach(btn=>btn.onclick=()=>{const next=phrases(input.value);next.splice(Number(btn.dataset.index),1);dispatchValue(input,encodePhrases(next));render(editor,input)})}
function escapeHtml(v){return String(v).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function enhance(drawer){
  if(drawer.querySelector('.multi-trigger-editor'))return
  const labels=[...drawer.querySelectorAll('.drawer-body>label')],keywordLabel=labels.find(l=>l.firstChild?.textContent?.trim()==='Keyword')
  if(!keywordLabel)return
  const input=keywordLabel.querySelector('input');if(!input)return
  keywordLabel.style.display='none'
  const editor=document.createElement('section');editor.className='multi-trigger-editor';editor.innerHTML='<label>Trigger words / phrases</label><div class="trigger-chips"></div><p class="trigger-empty">No trigger phrases yet.</p><div class="trigger-add"><input type="text" maxlength="255" placeholder="Add trigger phrase…"><button type="button">+ Add</button></div><p class="trigger-help">Exact match · case-insensitive · leading/trailing spaces ignored</p><p class="trigger-error" hidden></p>'
  keywordLabel.after(editor);render(editor,input)
  const addInput=editor.querySelector('.trigger-add input'),addButton=editor.querySelector('.trigger-add button'),error=editor.querySelector('.trigger-error')
  const add=async()=>{const value=addInput.value.trim();if(!value||busy)return;error.hidden=true;if(phrases(input.value).some(v=>v.toLowerCase()===value.toLowerCase())){error.textContent='That trigger phrase is already on this flow.';error.hidden=false;return}busy=true;addButton.disabled=true;try{const owner=await duplicateOwner(drawer,value);if(owner){error.textContent=`“${value}” is already used by active flow #${owner.id} · ${owner.name}.`;error.hidden=false;return}const next=[...phrases(input.value),value];const encoded=encodePhrases(next);if(encoded.length>255){error.textContent='Trigger phrases currently have a combined storage limit of 255 characters.';error.hidden=false;return}dispatchValue(input,encoded);addInput.value='';render(editor,input)}finally{busy=false;addButton.disabled=false}}
  addButton.onclick=add;addInput.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();add()}}
}
function scan(){document.querySelectorAll('.vfb .drawer').forEach(drawer=>{const type=drawer.querySelector('.drawer-head h2')?.textContent?.trim();if(type==='Start Bot Flow')enhance(drawer)})}
export function installFlowTriggerExtras(){const observer=new MutationObserver(()=>requestAnimationFrame(scan));observer.observe(document.body,{subtree:true,childList:true});scan();window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})}
