<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from './api'

const view = ref('inbox')
const conversations = ref([])
const messages = ref([])
const connections = ref([])
const selectedId = ref(null)
const loading = ref(false)
const sending = ref(false)
const savingConnection = ref(false)
const error = ref('')
const success = ref('')
const reply = ref('')
const messagePane = ref(null)
const connectionForm = ref({
  workspace_name: 'Default Workspace',
  workspace_slug: 'default',
  waba_id: '',
  account_name: '',
  phone_number_id: '',
  display_phone_number: '',
  verified_name: '',
  access_token: '',
})

const selectedConversation = computed(() => conversations.value.find((item) => item.id === selectedId.value) || null)

async function scrollToBottom() {
  await nextTick()
  if (messagePane.value) messagePane.value.scrollTop = messagePane.value.scrollHeight
}

async function loadConversations() {
  try {
    conversations.value = await api.conversations()
    if (!selectedId.value && conversations.value.length) await selectConversation(conversations.value[0].id)
  } catch (err) { error.value = err.message }
}

async function selectConversation(id) {
  selectedId.value = id
  loading.value = true
  error.value = ''
  try {
    messages.value = await api.messages(id)
    await scrollToBottom()
  } catch (err) { error.value = err.message }
  finally { loading.value = false }
}

async function sendReply() {
  const conversation = selectedConversation.value
  const text = reply.value.trim()
  if (!conversation || !text || sending.value) return
  sending.value = true
  error.value = ''
  try {
    const message = await api.sendText(conversation.id, text)
    messages.value.push(message)
    reply.value = ''
    conversation.last_message_at = message.created_at
    await scrollToBottom()
  } catch (err) { error.value = err.message }
  finally { sending.value = false }
}

async function openSettings() {
  view.value = 'settings'
  error.value = ''
  success.value = ''
  try { connections.value = await api.whatsappConnections() }
  catch (err) { error.value = err.message }
}

async function saveConnection() {
  if (savingConnection.value) return
  savingConnection.value = true
  error.value = ''
  success.value = ''
  try {
    const created = await api.connectWhatsApp(connectionForm.value)
    connections.value.push(created)
    connectionForm.value = { ...connectionForm.value, waba_id: '', account_name: '', phone_number_id: '', display_phone_number: '', verified_name: '', access_token: '' }
    success.value = 'WhatsApp Business number connected. Configure the Meta webhook next.'
  } catch (err) { error.value = err.message }
  finally { savingConnection.value = false }
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

onMounted(loadConversations)
</script>

<template>
  <main class="shell" :class="{ 'settings-view': view === 'settings' }">
    <aside class="sidebar">
      <div class="brand"><div class="logo">WA</div><div><strong>WA Connect</strong><span>WhatsApp Core v0.1.0</span></div></div>
      <nav class="nav">
        <button :class="{ active: view === 'inbox' }" @click="view = 'inbox'">Inbox</button>
        <button disabled>Contacts</button><button disabled>Flows</button><button disabled>Campaigns</button>
        <button :class="{ active: view === 'settings' }" @click="openSettings">Settings</button>
      </nav>
    </aside>

    <template v-if="view === 'inbox'">
      <section class="conversation-list">
        <header><div><p class="eyebrow">Live chat</p><h1>Inbox</h1></div><button class="refresh" @click="loadConversations">↻</button></header>
        <div v-if="!conversations.length" class="empty-list">No conversations yet. Incoming WhatsApp messages will appear here.</div>
        <button v-for="conversation in conversations" :key="conversation.id" class="conversation-row" :class="{ selected: selectedId === conversation.id }" @click="selectConversation(conversation.id)">
          <span class="avatar">{{ (conversation.contact.name || conversation.contact.wa_id).slice(0, 1).toUpperCase() }}</span>
          <span class="conversation-copy"><strong>{{ conversation.contact.name || conversation.contact.wa_id }}</strong><small>{{ conversation.contact.wa_id }}</small></span>
          <span class="status">{{ conversation.status }}</span>
        </button>
      </section>

      <section class="chat-panel">
        <template v-if="selectedConversation">
          <header class="chat-header"><div><strong>{{ selectedConversation.contact.name || selectedConversation.contact.wa_id }}</strong><span>{{ selectedConversation.contact.wa_id }}</span></div><span class="status-pill">{{ selectedConversation.status }}</span></header>
          <div ref="messagePane" class="messages">
            <div v-if="loading" class="center-state">Loading messages…</div>
            <article v-for="message in messages" :key="message.id" class="bubble" :class="message.direction"><p>{{ message.body || `[${message.message_type}]` }}</p><footer><span>{{ formatTime(message.whatsapp_timestamp || message.created_at) }}</span><span>{{ message.status }}</span></footer></article>
          </div>
          <form class="composer" @submit.prevent="sendReply"><textarea v-model="reply" rows="1" placeholder="Type a WhatsApp reply…" /><button type="submit" :disabled="sending || !reply.trim()">{{ sending ? 'Sending…' : 'Send' }}</button></form>
        </template>
        <div v-else class="center-state">Select a conversation to start chatting.</div>
        <div v-if="error" class="error-banner">{{ error }}</div>
      </section>

      <aside class="contact-panel"><template v-if="selectedConversation"><div class="large-avatar">{{ (selectedConversation.contact.name || selectedConversation.contact.wa_id).slice(0, 1).toUpperCase() }}</div><h2>{{ selectedConversation.contact.name || 'WhatsApp Contact' }}</h2><p>{{ selectedConversation.contact.wa_id }}</p><hr /><dl><div><dt>Status</dt><dd>{{ selectedConversation.status }}</dd></div><div><dt>Channel</dt><dd>WhatsApp</dd></div></dl></template></aside>
    </template>

    <section v-else class="settings-page">
      <header class="settings-header"><div><p class="eyebrow">Configuration</p><h1>WhatsApp Business</h1><p>Connect a Meta WhatsApp Business Account and phone number to WA Connect.</p></div></header>
      <div class="settings-grid">
        <form class="settings-card" @submit.prevent="saveConnection">
          <h2>Connect number</h2><p class="muted">Use the IDs and permanent access token from your Meta app / WhatsApp API setup.</p>
          <div class="form-grid">
            <label>Workspace name<input v-model="connectionForm.workspace_name" required /></label>
            <label>Workspace slug<input v-model="connectionForm.workspace_slug" required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" /></label>
            <label>WABA ID<input v-model="connectionForm.waba_id" required /></label>
            <label>Account name<input v-model="connectionForm.account_name" placeholder="Optional" /></label>
            <label>Phone number ID<input v-model="connectionForm.phone_number_id" required /></label>
            <label>Display phone number<input v-model="connectionForm.display_phone_number" placeholder="e.g. +27 82 123 4567" /></label>
            <label>Verified name<input v-model="connectionForm.verified_name" placeholder="Optional" /></label>
            <label class="wide">Permanent access token<input v-model="connectionForm.access_token" type="password" required autocomplete="off" /></label>
          </div>
          <button class="primary" type="submit" :disabled="savingConnection">{{ savingConnection ? 'Connecting…' : 'Connect WhatsApp number' }}</button>
          <p v-if="success" class="success-message">{{ success }}</p><p v-if="error" class="form-error">{{ error }}</p>
        </form>

        <div class="settings-card">
          <h2>Connected numbers</h2>
          <div v-if="!connections.length" class="empty-list">No WhatsApp numbers connected yet.</div>
          <article v-for="connection in connections" :key="connection.id" class="connection-row">
            <div><strong>{{ connection.verified_name || connection.account_name || connection.display_phone_number || connection.phone_number_id }}</strong><span>{{ connection.display_phone_number || 'Phone ID ' + connection.phone_number_id }}</span></div>
            <div class="connection-meta"><span class="status-pill">{{ connection.active ? 'active' : 'inactive' }}</span><small>WABA {{ connection.waba_id }}</small><small>{{ connection.workspace_name }}</small></div>
          </article>
        </div>
      </div>
    </section>
  </main>
</template>
