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
  sendText: (conversationId, text) => request(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  }),
  whatsappConnections: () => request('/settings/whatsapp'),
  connectWhatsApp: (payload) => request('/settings/whatsapp', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
}
