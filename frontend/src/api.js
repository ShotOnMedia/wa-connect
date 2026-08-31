const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

function formatApiError(detail, fallback) {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const location = Array.isArray(item.loc) ? item.loc.filter(part => part !== 'body').join('.') : ''
        const message = item.msg || item.message || JSON.stringify(item)
        return location ? `${location}: ${message}` : message
      }
      return String(item)
    }).join('; ')
  }
  if (typeof detail === 'object') return detail.message || detail.msg || JSON.stringify(detail)
  return String(detail)
}

async function request(path,options={}){const response=await fetch(`${API_BASE}${path}`,{credentials:'include',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});if(!response.ok){const payload=await response.json().catch(()=>({}));const error=new Error(formatApiError(payload.detail,`Request failed (${response.status})`));error.status=response.status;error.payload=payload;throw error}if(response.status===204)return null;return response.json()}
export const api={
me:()=>request('/auth/me'),login:(email,password)=>request('/auth/login',{method:'POST',body:JSON.stringify({email,password})}),logout:()=>request('/auth/logout',{method:'POST'}),
conversations:(assignment='all')=>request(`/conversations?assignment=${encodeURIComponent(assignment)}`),messages:id=>request(`/conversations/${id}/messages`),markRead:id=>request(`/conversations/${id}/read`,{method:'POST'}),setConversationStatus:(id,status)=>request(`/conversations/${id}/status`,{method:'PATCH',body:JSON.stringify({status})}),assignConversation:(id,userId)=>request(`/conversations/${id}/assignment`,{method:'PATCH',body:JSON.stringify({user_id:userId})}),sendText:(id,text)=>request(`/conversations/${id}/messages`,{method:'POST',body:JSON.stringify({text})}),flowSession:id=>request(`/conversations/${id}/flow-session`),resetFlowSession:id=>request(`/conversations/${id}/flow-session/reset`,{method:'POST'}),
contacts:(query='',tagId=null,lifecycle='active')=>{const params=new URLSearchParams();if(query)params.set('q',query);if(tagId)params.set('tag_id',tagId);if(lifecycle)params.set('lifecycle',lifecycle);const suffix=params.toString()?`?${params}`:'';return request(`/contacts${suffix}`)},contact:id=>request(`/contacts/${id}`),updateContact:(id,payload)=>request(`/contacts/${id}`,{method:'PATCH',body:JSON.stringify(payload)}),updateContactLifecycle:(id,payload)=>request(`/contacts/${id}/lifecycle`,{method:'PATCH',body:JSON.stringify(payload)}),
contactTags:()=>request('/contacts/tags'),createContactTag:name=>request('/contacts/tags',{method:'POST',body:JSON.stringify({name})}),addContactTag:(cid,tid)=>request(`/contacts/${cid}/tags/${tid}`,{method:'POST'}),removeContactTag:(cid,tid)=>request(`/contacts/${cid}/tags/${tid}`,{method:'DELETE'}),addContactNote:(id,body)=>request(`/contacts/${id}/notes`,{method:'POST',body:JSON.stringify({body})}),deleteContactNote:(cid,nid)=>request(`/contacts/${cid}/notes/${nid}`,{method:'DELETE'}),
contactFields:()=>request('/contact-fields'),createContactField:payload=>request('/contact-fields',{method:'POST',body:JSON.stringify(payload)}),updateContactField:(id,payload)=>request(`/contact-fields/${id}`,{method:'PATCH',body:JSON.stringify(payload)}),deleteContactField:id=>request(`/contact-fields/${id}`,{method:'DELETE'}),contactCustomFields:id=>request(`/contacts/${id}/custom-fields`),setContactCustomField:(cid,fid,value)=>request(`/contacts/${cid}/custom-fields/${fid}`,{method:'PUT',body:JSON.stringify({value})}),
flows:(status=null)=>request(`/flows${status?`?status=${encodeURIComponent(status)}`:''}`),flow:id=>request(`/flows/${id}`),createFlow:payload=>request('/flows',{method:'POST',body:JSON.stringify(payload)}),updateFlow:(id,payload)=>request(`/flows/${id}`,{method:'PATCH',body:JSON.stringify(payload)}),deleteFlow:id=>request(`/flows/${id}`,{method:'DELETE'}),addFlowStep:(id,payload)=>request(`/flows/${id}/steps`,{method:'POST',body:JSON.stringify(payload)}),updateFlowStep:(fid,sid,payload)=>request(`/flows/${fid}/steps/${sid}`,{method:'PATCH',body:JSON.stringify(payload)}),deleteFlowStep:(fid,sid)=>request(`/flows/${fid}/steps/${sid}`,{method:'DELETE'}),reorderFlowSteps:(id,stepIds)=>request(`/flows/${id}/steps-order`,{method:'POST',body:JSON.stringify({step_ids:stepIds})}),
flowGraph:id=>request(`/flows/${id}/graph`),addFlowNode:(id,payload)=>request(`/flows/${id}/nodes`,{method:'POST',body:JSON.stringify(payload)}),updateFlowNode:(fid,nid,payload)=>request(`/flows/${fid}/nodes/${nid}`,{method:'PATCH',body:JSON.stringify(payload)}),deleteFlowNode:(fid,nid)=>request(`/flows/${fid}/nodes/${nid}`,{method:'DELETE'}),addFlowEdge:(id,payload)=>request(`/flows/${id}/edges`,{method:'POST',body:JSON.stringify(payload)}),deleteFlowEdge:(fid,eid)=>request(`/flows/${fid}/edges/${eid}`,{method:'DELETE'}),
users:()=>request('/users'),agents:()=>request('/users/agents'),createUser:payload=>request('/users',{method:'POST',body:JSON.stringify(payload)}),updateUser:(id,payload)=>request(`/users/${id}`,{method:'PATCH',body:JSON.stringify(payload)}),whatsappConnections:()=>request('/settings/whatsapp'),webhookSetup:()=>request('/settings/whatsapp/webhook'),verifyWhatsApp:payload=>request('/settings/whatsapp/verify',{method:'POST',body:JSON.stringify(payload)}),whatsappHealth:id=>request(`/settings/whatsapp/${id}/health`),connectWhatsApp:payload=>request('/settings/whatsapp',{method:'POST',body:JSON.stringify(payload)}),
telegramStats:()=>request('/telegram/stats'),telegramBots:()=>request('/telegram/bots'),verifyTelegram:bot_token=>request('/telegram/verify',{method:'POST',body:JSON.stringify({bot_token})}),connectTelegram:payload=>request('/telegram/bots',{method:'POST',body:JSON.stringify(payload)}),telegramHealth:id=>request(`/telegram/bots/${id}/health`)}
