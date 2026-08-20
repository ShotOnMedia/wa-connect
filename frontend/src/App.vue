<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'

const conversations = ref([])
const messages = ref([])
const selectedId = ref(null)
const loading = ref(false)
const error = ref('')
const reply = ref('')

const selectedConversation = computed(() =>
  conversations.value.find((item) => item.id === selectedId.value) || null,
)

async function loadConversations() {
  try {
    conversations.value = await api.conversations()
    if (!selectedId.value && conversations.value.length) {
      await selectConversation(conversations.value[0].id)
    }
  } catch (err) {
    error.value = err.message
  }
}

async function selectConversation(id) {
  selectedId.value = id
  loading.value = true
  error.value = ''
  try {
    messages.value = await api.messages(id)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function sendReply() {
  const conversation = selectedConversation.value
  const text = reply.value.trim()
  if (!conversation || !text) return

  error.value = 'Reply endpoint is wired, but the inbox still needs phone-number metadata before live sending can be enabled.'
}

function formatTime(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

onMounted(loadConversations)
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="logo">WA</div>
        <div>
          <strong>WA Connect</strong>
          <span>WhatsApp Core v0.1.0</span>
        </div>
      </div>

      <nav class="nav">
        <button class="active">Inbox</button>
        <button disabled>Contacts</button>
        <button disabled>Flows</button>
        <button disabled>Campaigns</button>
      </nav>
    </aside>

    <section class="conversation-list">
      <header>
        <div>
          <p class="eyebrow">Live chat</p>
          <h1>Inbox</h1>
        </div>
        <button class="refresh" @click="loadConversations">↻</button>
      </header>

      <div v-if="!conversations.length" class="empty-list">
        No conversations yet. Incoming WhatsApp messages will appear here.
      </div>

      <button
        v-for="conversation in conversations"
        :key="conversation.id"
        class="conversation-row"
        :class="{ selected: selectedId === conversation.id }"
        @click="selectConversation(conversation.id)"
      >
        <span class="avatar">{{ (conversation.contact.name || conversation.contact.wa_id).slice(0, 1).toUpperCase() }}</span>
        <span class="conversation-copy">
          <strong>{{ conversation.contact.name || conversation.contact.wa_id }}</strong>
          <small>{{ conversation.contact.wa_id }}</small>
        </span>
        <span class="status">{{ conversation.status }}</span>
      </button>
    </section>

    <section class="chat-panel">
      <template v-if="selectedConversation">
        <header class="chat-header">
          <div>
            <strong>{{ selectedConversation.contact.name || selectedConversation.contact.wa_id }}</strong>
            <span>{{ selectedConversation.contact.wa_id }}</span>
          </div>
          <span class="status-pill">{{ selectedConversation.status }}</span>
        </header>

        <div class="messages">
          <div v-if="loading" class="center-state">Loading messages…</div>
          <article
            v-for="message in messages"
            :key="message.id"
            class="bubble"
            :class="message.direction"
          >
            <p>{{ message.body || `[${message.message_type}]` }}</p>
            <footer>
              <span>{{ formatTime(message.whatsapp_timestamp || message.created_at) }}</span>
              <span>{{ message.status }}</span>
            </footer>
          </article>
        </div>

        <form class="composer" @submit.prevent="sendReply">
          <textarea v-model="reply" rows="1" placeholder="Type a WhatsApp reply…" />
          <button type="submit">Send</button>
        </form>
      </template>

      <div v-else class="center-state">Select a conversation to start chatting.</div>

      <div v-if="error" class="error-banner">{{ error }}</div>
    </section>

    <aside class="contact-panel">
      <template v-if="selectedConversation">
        <div class="large-avatar">
          {{ (selectedConversation.contact.name || selectedConversation.contact.wa_id).slice(0, 1).toUpperCase() }}
        </div>
        <h2>{{ selectedConversation.contact.name || 'WhatsApp Contact' }}</h2>
        <p>{{ selectedConversation.contact.wa_id }}</p>
        <hr />
        <dl>
          <div><dt>Status</dt><dd>{{ selectedConversation.status }}</dd></div>
          <div><dt>Channel</dt><dd>WhatsApp</dd></div>
        </dl>
      </template>
    </aside>
  </main>
</template>
