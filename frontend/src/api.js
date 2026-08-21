const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const error = new Error(payload.detail || `Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  if (response.status === 204) return null
  return response.json()
}

export const api = {
  me: () => request('/auth/me'),
  login: (email, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  conversations: (assignment = 'all') => request(`/conversations?assignment=${encodeURIComponent(assignment)}`),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages`),
  markRead: (conversationId) => request(`/conversations/${conversationId}/read`, { method: 'POST' }),
  setConversationStatus: (conversationId, status) => request(`/conversations/${conversationId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  assignConversation: (conversationId, userId) => request(`/conversations/${conversationId}/assignment`, { method: 'PATCH', body: JSON.stringify({ user_id: userId }) }),
  sendText: (conversationId, text) => request(`/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ text }) }),
  contacts: (query = '') => request(`/contacts${query ? `?q=${encodeURIComponent(query)}` : ''}`),
  contact: (contactId) => request(`/contacts/${contactId}`),
  updateContact: (contactId, payload) => request(`/contacts/${contactId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  users: () => request('/users'),
  agents: () => request('/users/agents'),
  createUser: (payload) => request('/users', { method: 'POST', body: JSON.stringify(payload) }),
  updateUser: (userId, payload) => request(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  whatsappConnections: () => request('/settings/whatsapp'),
  webhookSetup: () => request('/settings/whatsapp/webhook'),
  verifyWhatsApp: (payload) => request('/settings/whatsapp/verify', { method: 'POST', body: JSON.stringify(payload) }),
  whatsappHealth: (connectionId) => request(`/settings/whatsapp/${connectionId}/health`),
  connectWhatsApp: (payload) => request('/settings/whatsapp', { method: 'POST', body: JSON.stringify(payload) }),
}
