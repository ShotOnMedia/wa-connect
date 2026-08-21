const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `Request failed (${response.status})`)
  }
  return response.json()
}

export const api = {
  conversations: () => request('/conversations'),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages`),
  markRead: (conversationId) => request(`/conversations/${conversationId}/read`, { method: 'POST' }),
  setConversationStatus: (conversationId, status) => request(`/conversations/${conversationId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  sendText: (conversationId, text) => request(`/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ text }) }),
  whatsappConnections: () => request('/settings/whatsapp'),
  webhookSetup: () => request('/settings/whatsapp/webhook'),
  verifyWhatsApp: (payload) => request('/settings/whatsapp/verify', { method: 'POST', body: JSON.stringify(payload) }),
  whatsappHealth: (connectionId) => request(`/settings/whatsapp/${connectionId}/health`),
  connectWhatsApp: (payload) => request('/settings/whatsapp', { method: 'POST', body: JSON.stringify(payload) }),
}
