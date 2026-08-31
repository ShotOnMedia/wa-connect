<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from './api'
import App from './App.vue'

const props = defineProps({ currentUser: { type: Object, required: true } })
const emit = defineEmits(['logout'])

const section = ref('dashboard')
const whatsappView = ref('inbox')
const settingsView = ref('users')
const whatsappOpen = ref(true)
const telegramOpen = ref(true)
const settingsOpen = ref(true)
const stats = ref({ contacts: 0, conversations: 0, flows: 0, activeFlows: 0, unread: 0 })
const statsLoading = ref(false)
const statsError = ref('')

const canManageFlows = computed(() => ['admin', 'manager'].includes(props.currentUser.role))
const canManageUsers = computed(() => props.currentUser.role === 'admin')

async function loadDashboard() {
  statsLoading.value = true
  statsError.value = ''
  try {
    const [contacts, conversations, flows] = await Promise.all([
      api.contacts('', null, 'all'),
      api.conversations('all'),
      canManageFlows.value ? api.flows() : Promise.resolve([]),
    ])
    stats.value = {
      contacts: contacts.length,
      conversations: conversations.length,
      flows: flows.length,
      activeFlows: flows.filter(flow => flow.status === 'active').length,
      unread: conversations.reduce((sum, item) => sum + (item.unread_count || 0), 0),
    }
  } catch (err) {
    statsError.value = err.message
  } finally {
    statsLoading.value = false
  }
}

function openDashboard() {
  section.value = 'dashboard'
  loadDashboard()
}

async function openWhatsApp(view) {
  section.value = 'whatsapp'
  whatsappView.value = view
  await nextTick()
  // Transitional bridge while the original WhatsApp screen is split into channel-neutral components.
  const buttons = [...document.querySelectorAll('.channel-app .nav button')]
  const labels = { inbox: 'Inbox', contacts: 'Contacts', flows: 'Flows', settings: 'Settings' }
  const target = buttons.find(button => button.textContent.trim().startsWith(labels[view]))
  if (target) target.click()
}

async function openGlobalSettings(view = 'users') {
  section.value = 'settings'
  settingsView.value = view
  await nextTick()
  const buttons = [...document.querySelectorAll('.settings-app .nav button')]
  const target = buttons.find(button => button.textContent.trim().startsWith('Users'))
  if (target) target.click()
}

function openTelegram(view) {
  section.value = 'telegram'
  whatsappView.value = view
}

onMounted(loadDashboard)
</script>

<template>
  <main class="platform-shell">
    <aside class="platform-sidebar">
      <div class="platform-brand">
        <div class="platform-logo">WA</div>
        <div><strong>WA Connect</strong><span>Multi-channel v0.2.0</span></div>
      </div>

      <nav class="platform-nav">
        <button class="top-link" :class="{ active: section === 'dashboard' }" @click="openDashboard"><span>▦</span> Dashboard</button>

        <div class="nav-group">
          <button class="group-title" :class="{ active: section === 'whatsapp' }" @click="whatsappOpen = !whatsappOpen"><span class="channel-dot whatsapp">W</span><b>WhatsApp</b><i>{{ whatsappOpen ? '⌃' : '⌄' }}</i></button>
          <div v-if="whatsappOpen" class="subnav">
            <button :class="{ active: section === 'whatsapp' && whatsappView === 'inbox' }" @click="openWhatsApp('inbox')">Live Chat</button>
            <button :class="{ active: section === 'whatsapp' && whatsappView === 'contacts' }" @click="openWhatsApp('contacts')">Contacts</button>
            <button v-if="canManageFlows" :class="{ active: section === 'whatsapp' && whatsappView === 'flows' }" @click="openWhatsApp('flows')">Flows</button>
            <button v-if="currentUser.role === 'admin'" :class="{ active: section === 'whatsapp' && whatsappView === 'settings' }" @click="openWhatsApp('settings')">Settings</button>
          </div>
        </div>

        <div class="nav-group">
          <button class="group-title" :class="{ active: section === 'telegram' }" @click="telegramOpen = !telegramOpen"><span class="channel-dot telegram">T</span><b>Telegram</b><i>{{ telegramOpen ? '⌃' : '⌄' }}</i></button>
          <div v-if="telegramOpen" class="subnav">
            <button :class="{ active: section === 'telegram' && whatsappView === 'inbox' }" @click="openTelegram('inbox')">Live Chat</button>
            <button :class="{ active: section === 'telegram' && whatsappView === 'contacts' }" @click="openTelegram('contacts')">Contacts</button>
            <button v-if="canManageFlows" :class="{ active: section === 'telegram' && whatsappView === 'flows' }" @click="openTelegram('flows')">Flows</button>
            <button v-if="currentUser.role === 'admin'" :class="{ active: section === 'telegram' && whatsappView === 'settings' }" @click="openTelegram('settings')">Settings</button>
          </div>
        </div>

        <div v-if="canManageUsers" class="nav-group">
          <button class="group-title" :class="{ active: section === 'settings' }" @click="settingsOpen = !settingsOpen"><span>⚙</span><b>Settings</b><i>{{ settingsOpen ? '⌃' : '⌄' }}</i></button>
          <div v-if="settingsOpen" class="subnav"><button :class="{ active: section === 'settings' && settingsView === 'users' }" @click="openGlobalSettings('users')">Users</button></div>
        </div>
      </nav>

      <div class="platform-user"><span class="user-avatar">{{ currentUser.name.slice(0,1).toUpperCase() }}</span><div><strong>{{ currentUser.name }}</strong><small>{{ currentUser.role }}</small></div><button title="Log out" @click="emit('logout')">↪</button></div>
    </aside>

    <section v-if="section === 'dashboard'" class="dashboard-page">
      <header class="dashboard-header"><div><p class="dash-eyebrow">Overview</p><h1>Dashboard</h1><p>Your messaging channels at a glance.</p></div><button @click="loadDashboard">{{ statsLoading ? 'Refreshing…' : '↻ Refresh' }}</button></header>
      <div class="channel-heading"><div class="channel-icon whatsapp">W</div><div><h2>WhatsApp Stats</h2><p>Current activity across your WhatsApp workspace.</p></div></div>
      <div class="stats-grid">
        <article><span>Contacts</span><strong>{{ stats.contacts }}</strong><small>WhatsApp contacts</small></article>
        <article><span>Conversations</span><strong>{{ stats.conversations }}</strong><small>Total conversations</small></article>
        <article><span>Flows</span><strong>{{ stats.flows }}</strong><small>{{ stats.activeFlows }} active</small></article>
        <article><span>Unread</span><strong>{{ stats.unread }}</strong><small>Messages needing attention</small></article>
      </div>
      <p v-if="statsError" class="dashboard-error">{{ statsError }}</p>
      <div class="telegram-preview"><div class="channel-heading"><div class="channel-icon telegram">T</div><div><h2>Telegram Stats</h2><p>Ready for the Telegram Bot API connection.</p></div></div><div class="empty-channel"><strong>Telegram foundation is next</strong><span>Connect a bot to start collecting contacts, conversations and flow activity.</span><button @click="openTelegram('settings')">Open Telegram setup →</button></div></div>
    </section>

    <section v-else-if="section === 'telegram'" class="telegram-page">
      <header><p class="dash-eyebrow">Telegram</p><h1>{{ whatsappView === 'inbox' ? 'Live Chat' : whatsappView.charAt(0).toUpperCase() + whatsappView.slice(1) }}</h1><p>The Telegram channel shell is ready. Bot connection and webhook transport are the next build step.</p></header>
      <div class="telegram-scaffold"><div class="telegram-mark">T</div><h2>{{ whatsappView === 'settings' ? 'Connect your Telegram bot' : 'Telegram ' + (whatsappView === 'inbox' ? 'Live Chat' : whatsappView) }}</h2><p v-if="whatsappView === 'settings'">We’ll connect a bot token, verify it with Telegram and register the WA Connect webhook here.</p><p v-else>This screen will use the same WA Connect concepts as WhatsApp, backed by Telegram contacts and conversations.</p><span>v0.2.0 · Telegram Core</span></div>
    </section>

    <section v-else-if="section === 'settings'" class="embedded-app settings-app"><App :current-user="currentUser" @logout="emit('logout')" /></section>
    <section v-else class="embedded-app channel-app"><App :current-user="currentUser" @logout="emit('logout')" /></section>
  </main>
</template>

<style>
.platform-shell{min-height:100vh;background:#f4f7f6;color:#13251d}.platform-sidebar{position:fixed;inset:0 auto 0 0;width:220px;background:#0b2b20;color:#d9e8e1;display:flex;flex-direction:column;z-index:100}.platform-brand{display:flex;align-items:center;gap:12px;padding:22px 16px 20px}.platform-brand strong,.platform-brand span{display:block}.platform-brand strong{color:#fff;font-size:16px}.platform-brand span{font-size:11px;color:#89a99c;margin-top:2px}.platform-logo{width:40px;height:40px;border-radius:11px;background:#25d366;color:#062b1b;font-weight:900;display:grid;place-items:center}.platform-nav{padding:6px 12px;display:flex;flex-direction:column;gap:7px}.platform-nav button{font:inherit;color:inherit;border:0;background:transparent;cursor:pointer;text-align:left}.top-link,.group-title{width:100%;min-height:42px;border-radius:10px!important;padding:0 12px!important;display:flex;align-items:center;gap:10px}.top-link.active,.group-title.active{background:#194738!important;color:#fff}.group-title b{font-weight:600;flex:1}.group-title i{font-style:normal;color:#7fa395}.channel-dot{width:23px;height:23px;border-radius:7px;display:grid;place-items:center;font-size:11px;font-weight:800}.channel-dot.whatsapp,.channel-icon.whatsapp{background:#25d366;color:#07331f}.channel-dot.telegram,.channel-icon.telegram{background:#229ed9;color:white}.subnav{margin:4px 0 4px 35px;border-left:1px solid #285344;padding-left:8px;display:flex;flex-direction:column}.subnav button{padding:8px 10px!important;border-radius:7px!important;font-size:13px;color:#a9c0b7}.subnav button:hover,.subnav button.active{color:#fff;background:#143d30!important}.platform-user{margin:auto 14px 18px;padding-top:16px;border-top:1px solid #285044;display:flex;align-items:center;gap:10px}.platform-user div{flex:1}.platform-user strong,.platform-user small{display:block}.platform-user small{font-size:10px;color:#8ba99e;margin-top:2px}.platform-user button{border:0;background:transparent;color:#9eb7ae;font-size:18px;cursor:pointer}.user-avatar{width:34px;height:34px;border-radius:50%;background:#d8f4e7;color:#0c5235;display:grid;place-items:center;font-weight:800}.dashboard-page,.telegram-page{margin-left:220px;min-height:100vh;padding:34px 38px}.dashboard-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:32px}.dashboard-header h1,.telegram-page h1{font-size:30px;margin:2px 0 5px}.dashboard-header p,.telegram-page header>p:last-child,.channel-heading p{margin:0;color:#74867e}.dashboard-header button{border:1px solid #d5dfdb;background:#fff;border-radius:9px;padding:10px 14px;cursor:pointer}.dash-eyebrow{margin:0!important;text-transform:uppercase;color:#119052!important;font-size:11px;font-weight:800;letter-spacing:.08em}.channel-heading{display:flex;align-items:center;gap:13px;margin-bottom:15px}.channel-heading h2{margin:0 0 3px;font-size:19px}.channel-icon{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;font-weight:900}.stats-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px;margin-bottom:34px}.stats-grid article{background:#fff;border:1px solid #dfe7e3;border-radius:14px;padding:20px;box-shadow:0 3px 14px rgba(21,57,43,.04)}.stats-grid span,.stats-grid small{display:block;color:#788a82}.stats-grid span{font-size:13px}.stats-grid strong{display:block;font-size:31px;margin:9px 0 5px}.stats-grid small{font-size:11px}.telegram-preview{border-top:1px solid #dce5e1;padding-top:28px}.empty-channel,.telegram-scaffold{background:#fff;border:1px dashed #cfdcd6;border-radius:14px;padding:28px}.empty-channel strong,.empty-channel span{display:block}.empty-channel span{color:#75867f;margin:7px 0 16px}.empty-channel button{border:0;background:#229ed9;color:#fff;border-radius:8px;padding:10px 14px;cursor:pointer}.dashboard-error{background:#fff0f0;color:#9c2929;border:1px solid #f1caca;padding:10px 14px;border-radius:8px}.telegram-page header{margin-bottom:26px}.telegram-scaffold{text-align:center;max-width:720px;margin:70px auto}.telegram-mark{width:60px;height:60px;margin:0 auto 16px;border-radius:18px;background:#229ed9;color:#fff;display:grid;place-items:center;font-size:25px;font-weight:900}.telegram-scaffold h2{margin:0 0 9px}.telegram-scaffold p{color:#74867e;max-width:520px;margin:0 auto 20px;line-height:1.55}.telegram-scaffold span{font-size:11px;color:#9aaba4}.embedded-app{margin-left:220px;min-height:100vh}.embedded-app .shell{margin-left:0!important}.embedded-app .shell>.sidebar{display:none!important}.embedded-app .shell{grid-template-columns:325px minmax(0,1fr) 300px!important;width:100%!important}.embedded-app .shell.wide-view{grid-template-columns:minmax(0,1fr)!important}.settings-app .shell>.settings-page,.channel-app .shell>.settings-page,.channel-app .shell>.contacts-page{grid-column:1/-1}@media(max-width:1000px){.stats-grid{grid-template-columns:repeat(2,1fr)}.platform-sidebar{width:190px}.dashboard-page,.telegram-page,.embedded-app{margin-left:190px}}@media(max-width:720px){.platform-sidebar{position:relative;width:100%;min-height:auto}.platform-user{display:none}.platform-shell{display:block}.dashboard-page,.telegram-page,.embedded-app{margin-left:0}.stats-grid{grid-template-columns:1fr}.dashboard-page,.telegram-page{padding:24px 18px}}
</style>
