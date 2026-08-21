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
  contacts: (query = '', tagId = null) => {
    const params = new URLSearchParams()
    if (query) params.set('q', query)
    if (tagId) params.set('tag_id', tagId)
    const suffix = params.toString() ? `?${params}` : ''
    return request(`/contacts${suffix}`)
  },
  contact: (contactId) => request(`/contacts/${contactId}`),
  updateContact: (contactId, payload) => request(`/contacts/${contactId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  contactTags: () => request('/contacts/tags'),
  createContactTag: (name) => request('/contacts/tags', { method: 'POST', body: JSON.stringify({ name }) }),
  addContactTag: (contactId, tagId) => request(`/contacts/${contactId}/tags/${tagId}`, { method: 'POST' }),
  removeContactTag: (contactId, tagId) => request(`/contacts/${contactId}/tags/${tagId}`, { method: 'DELETE' }),
  addContactNote: (contactId, body) => request(`/contacts/${contactId}/notes`, { method: 'POST', body: JSON.stringify({ body }) }),
  deleteContactNote: (contactId, noteId) => request(`/contacts/${contactId}/notes/${noteId}`, { method: 'DELETE' }),
  contactFields: () => request('/contact-fields'),
  createContactField: (payload) => request('/contact-fields', { method: 'POST', body: JSON.stringify(payload) }),
  updateContactField: (fieldId, payload) => request(`/contact-fields/${fieldId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteContactField: (fieldId) => request(`/contact-fields/${fieldId}`, { method: 'DELETE' }),
  contactCustomFields: (contactId) => request(`/contacts/${contactId}/custom-fields`),
  setContactCustomField: (contactId, fieldId, value) => request(`/contacts/${contactId}/custom-fields/${fieldId}`, { method: 'PUT', body: JSON.stringify({ value }) }),
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
