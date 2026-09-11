import { api } from './api'
import './live-chat-display.css'

const TZ_KEY='wa-connect-display-timezone'
const WA_ACCOUNT_KEY='wa-connect-wa-account-filter'
const TG_ACCOUNT_KEY='wa-connect-tg-account-filter'
const NativeDate=window.Date
const NativeDateTimeFormat=Intl.DateTimeFormat
let activeTimezone=localStorage.getItem(TZ_KEY)||''

function timezone(){return activeTimezone}
function normaliseUtcString(value){
  if(typeof value!=='string')return value
  const text=value.trim()
  if(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text))return `${text}Z`
  if(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text))return `${text.replace(' ','T')}Z`
  return value
}
function installUtcDateParsing(){if(window.__waConnectUtcDateInstalled)return;class UTCDate extends NativeDate{constructor(...args){super(...(args.length===1?[normaliseUtcString(args[0])]:args))}static parse(value){return NativeDate.parse(normaliseUtcString(value))}static UTC(...args){return NativeDate.UTC(...args)}static now(){return NativeDate.now()}}Object.setPrototypeOf(UTCDate,NativeDate);window.Date=UTCDate;window.__waConnectUtcDateInstalled=true}
function installTimezoneFormatter(){if(Intl.__waConnectTimezoneInstalled)return;function PatchedDateTimeFormat(locales,options={}){const zone=timezone(),opts={...(options||{})};if(zone&&!opts.timeZone)opts.timeZone=zone;return new NativeDateTimeFormat(locales,opts)}PatchedDateTimeFormat.prototype=NativeDateTimeFormat.prototype;Object.setPrototypeOf(PatchedDateTimeFormat,NativeDateTimeFormat);Intl.DateTimeFormat=PatchedDateTimeFormat;Intl.__waConnectTimezoneInstalled=true}
function validTimezone(value){if(!value)return true;try{new NativeDateTimeFormat('en',{timeZone:value}).format(new NativeDate());return true}catch(_){return false}}
function zones(){const browser=new NativeDateTimeFormat().resolvedOptions().timeZone;let all=[];try{all=Intl.supportedValuesOf?.('timeZone')||[]}catch(_){all=[]}const preferred=['UTC','Africa/Johannesburg','Europe/London','Europe/Paris','America/New_York','America/Chicago','America/Los_Angeles','Asia/Dubai','Asia/Kolkata','Asia/Singapore','Australia/Sydney'];return [...new Set([browser,...preferred,...all].filter(Boolean))]}
function esc(value=''){return String(value).replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[ch]))}
function rerenderTimes(){document.querySelectorAll('.live-chat-time-refresh').forEach(el=>el.remove());const marker=document.createElement('span');marker.className='live-chat-time-refresh';marker.hidden=true;document.body.appendChild(marker);window.dispatchEvent(new Event('wa-connect-timezone-change'));schedule()}
function settingsButton(header){
  if(header.querySelector('.live-chat-settings-button'))return
  const refresh=[...header.querySelectorAll('button')].find(b=>/↻|refresh/i.test(`${b.textContent} ${b.title||''} ${b.getAttribute('aria-label')||''}`))
  const button=document.createElement('button');button.type='button';button.className='live-chat-settings-button';button.title='Live chat settings';button.setAttribute('aria-label','Live chat settings');button.innerHTML='&#9881;'
  if(refresh)refresh.insertAdjacentElement('afterend',button);else header.appendChild(button)
  const panel=document.createElement('div');panel.className='live-chat-settings-popover';panel.hidden=true;const id=`wa-chat-timezone-${Math.random().toString(36).slice(2)}`
  panel.innerHTML=`<div class="lc-settings-head"><strong>Live chat settings</strong><button type="button" class="lc-settings-close" aria-label="Close">×</button></div><label>Timezone<span>Message times are stored in UTC and displayed in this timezone.</span></label><input class="live-chat-timezone" list="${id}" placeholder="Browser timezone" value="${esc(timezone())}"><datalist id="${id}">${zones().map(z=>`<option value="${esc(z)}"></option>`).join('')}</datalist><div class="lc-settings-actions"><button type="button" class="lc-settings-cancel">Cancel</button><button type="button" class="lc-settings-apply">Apply</button></div>`
  header.appendChild(panel)
  const input=panel.querySelector('.live-chat-timezone'),close=()=>{panel.hidden=true;button.classList.remove('active')},open=()=>{input.value=timezone();panel.hidden=false;button.classList.add('active');input.focus()}
  button.addEventListener('click',e=>{e.stopPropagation();panel.hidden?open():close()});panel.querySelector('.lc-settings-close').addEventListener('click',close);panel.querySelector('.lc-settings-cancel').addEventListener('click',close)
  panel.querySelector('.lc-settings-apply').addEventListener('click',()=>{const value=input.value.trim();if(!validTimezone(value)){input.setCustomValidity('Enter a valid IANA timezone, e.g. Africa/Johannesburg');input.reportValidity();return}input.setCustomValidity('');activeTimezone=value;if(value)localStorage.setItem(TZ_KEY,value);else localStorage.removeItem(TZ_KEY);close();rerenderTimes()})
  document.addEventListener('click',e=>{if(!panel.hidden&&!panel.contains(e.target)&&e.target!==button)close()})
}
function accountControl(channel,items,current){const wrap=document.createElement('div');wrap.className='live-chat-display-control account-control';const select=document.createElement('select');select.className='live-chat-account-filter';select.innerHTML=`<option value="">All accounts</option>${items.map(i=>`<option value="${esc(i.id)}" ${String(current)===String(i.id)?'selected':''}>${esc(i.label)}</option>`).join('')}`;wrap.innerHTML='<label>Account</label>';wrap.appendChild(select);select.addEventListener('change',()=>{const key=channel==='telegram'?TG_ACCOUNT_KEY:WA_ACCOUNT_KEY;if(select.value)localStorage.setItem(key,select.value);else localStorage.removeItem(key);schedule()});return wrap}
async function telegramToolbar(){const header=document.querySelector('.tg-list > header');if(!header)return;settingsButton(header);if(document.querySelector('.tg-list > .live-chat-display-tools'))return;const conversations=await api.telegramConversations().catch(()=>[]);const items=[...new Map(conversations.map(c=>[String(c.bot?.id||''),{id:String(c.bot?.id||''),label:c.bot?.username?`@${c.bot.username}`:(c.bot?.first_name||`Telegram bot #${c.bot?.id}`)}])).values()].filter(x=>x.id);const tools=document.createElement('div');tools.className='live-chat-display-tools';tools.append(accountControl('telegram',items,localStorage.getItem(TG_ACCOUNT_KEY)||''));header.after(tools)}
async function filterTelegramRows(){const list=document.querySelector('.tg-list');if(!list)return;const conversations=await api.telegramConversations().catch(()=>[]),selected=localStorage.getItem(TG_ACCOUNT_KEY)||'';const rows=[...list.querySelectorAll(':scope > .row')];rows.forEach((row,index)=>{const c=conversations[index];row.style.display=!selected||String(c?.bot?.id||'')===selected?'':'none'})}
function activeButtonValue(selector,fallback){const el=document.querySelector(`${selector} button.active`);return el?.textContent?.trim().toLowerCase()||fallback}
async function whatsappToolbar(){const header=document.querySelector('.conversation-list > header');if(!header)return;settingsButton(header);if(document.querySelector('.conversation-list > .live-chat-display-tools'))return;const assignment=activeButtonValue('.assignment-filters','all'),conversations=await api.conversations(assignment).catch(()=>[]);let labels={};try{const connections=await api.whatsappConnections();for(const c of connections||[]){const id=String(c.id||c.phone_number_id||'');if(id)labels[id]=c.display_phone_number||c.verified_name||c.name||`WhatsApp #${id}`}}catch(_){}const items=[...new Map(conversations.map(c=>{const id=String(c.phone_number_id||'');return[id,{id,label:labels[id]||`WhatsApp #${id}`}] })).values()].filter(x=>x.id);const tools=document.createElement('div');tools.className='live-chat-display-tools';tools.append(accountControl('whatsapp',items,localStorage.getItem(WA_ACCOUNT_KEY)||''));header.after(tools)}
async function filterWhatsappRows(){const list=document.querySelector('.conversation-list');if(!list)return;const assignment=activeButtonValue('.assignment-filters','all'),status=activeButtonValue('.filters','all'),selected=localStorage.getItem(WA_ACCOUNT_KEY)||'';let conversations=await api.conversations(assignment).catch(()=>[]);if(status!=='all')conversations=conversations.filter(c=>String(c.status).toLowerCase()===status);const rows=[...list.querySelectorAll(':scope > .conversation-row')];rows.forEach((row,index)=>{const c=conversations[index];row.style.display=!selected||String(c?.phone_number_id||'')===selected?'':'none'})}
let timer=null,busy=false
async function refresh(){if(busy)return;busy=true;try{await telegramToolbar();await whatsappToolbar();await filterTelegramRows();await filterWhatsappRows()}finally{busy=false}}
function schedule(){clearTimeout(timer);timer=setTimeout(()=>refresh().catch(()=>{}),100)}
export function installLiveChatDisplay(){installUtcDateParsing();installTimezoneFormatter();const observer=new MutationObserver(schedule);observer.observe(document.body,{subtree:true,childList:true,characterData:true});schedule();window.addEventListener('beforeunload',()=>observer.disconnect(),{once:true})}
