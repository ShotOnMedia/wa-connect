<script setup>
import { onMounted, ref } from 'vue'
import { api } from './api'

const bots = ref([])
const preview = ref(null)
const health = ref({})
const loading = ref(true)
const verifying = ref(false)
const saving = ref(false)
const error = ref('')
const success = ref('')
const form = ref({
  workspace_name: 'Default Workspace',
  workspace_slug: 'default',
  bot_token: '',
  webhook_base_url: window.location.origin,
})

async function loadBots() {
  loading.value = true
  error.value = ''
  try { bots.value = await api.telegramBots() }
  catch (err) { error.value = err.message }
  finally { loading.value = false }
}

async function verify() {
  if (!form.value.bot_token.trim() || verifying.value) return
  verifying.value = true
  error.value = ''
  success.value = ''
  preview.value = null
  try {
    preview.value = await api.verifyTelegram(form.value.bot_token.trim())
    success.value = 'Telegram bot verified successfully.'
  } catch (err) { error.value = err.message }
  finally { verifying.value = false }
}

async function connect() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const connected = await api.connectTelegram({ ...form.value, bot_token: form.value.bot_token.trim(), webhook_base_url: form.value.webhook_base_url.trim() })
    const index = bots.value.findIndex(item => item.bot_id === connected.bot_id)
    if (index >= 0) bots.value[index] = connected
    else bots.value.push(connected)
    preview.value = null
    form.value.bot_token = ''
    success.value = `@${connected.username || connected.first_name || connected.bot_id} is connected and the webhook is registered.`
  } catch (err) { error.value = err.message }
  finally { saving.value = false }
}

async function checkHealth(bot) {
  health.value = { ...health.value, [bot.id]: { loading: true } }
  try { health.value = { ...health.value, [bot.id]: await api.telegramHealth(bot.id) } }
  catch (err) { health.value = { ...health.value, [bot.id]: { connected: false, error: err.message } } }
}

onMounted(loadBots)
</script>

<template>
  <div class="tg-settings">
    <div class="tg-grid">
      <form class="tg-card" @submit.prevent="connect">
        <div class="tg-card-head"><div class="tg-icon">T</div><div><h2>Connect Telegram bot</h2><p>Paste the token from BotFather. WA Connect will verify the bot and register its webhook automatically.</p></div></div>
        <div class="tg-form-grid">
          <label>Workspace name<input v-model="form.workspace_name" required /></label>
          <label>Workspace slug<input v-model="form.workspace_slug" required /></label>
          <label class="wide">Bot token<input v-model="form.bot_token" type="password" autocomplete="off" placeholder="123456789:AA..." required /></label>
          <label class="wide">Public WA Connect URL<input v-model="form.webhook_base_url" type="url" placeholder="https://connect.example.com" required /><small>Telegram requires a publicly reachable HTTPS webhook.</small></label>
        </div>
        <div class="tg-actions"><button type="button" class="secondary" :disabled="verifying || !form.bot_token.trim()" @click="verify">{{ verifying ? 'Verifying…' : 'Test bot token' }}</button><button class="primary" :disabled="saving">{{ saving ? 'Connecting…' : 'Verify, connect & register webhook' }}</button></div>
        <div v-if="preview" class="tg-preview"><span class="tg-avatar">T</span><div><strong>{{ preview.first_name }}</strong><b>@{{ preview.username }}</b><small>Bot ID {{ preview.bot_id }}</small></div><i>Verified</i></div>
        <p v-if="success" class="tg-success">{{ success }}</p><p v-if="error" class="tg-error">{{ error }}</p>
      </form>

      <section class="tg-card bots-card">
        <div class="section-head"><div><p class="eyebrow">Connected</p><h2>Telegram bots</h2></div><button class="refresh" @click="loadBots">↻</button></div>
        <div v-if="loading" class="empty">Loading bots…</div>
        <div v-else-if="!bots.length" class="empty"><strong>No Telegram bot connected yet</strong><span>Create a bot with BotFather, copy its API token and connect it here.</span></div>
        <article v-for="bot in bots" :key="bot.id" class="bot-row">
          <span class="tg-avatar">T</span><div class="bot-copy"><strong>{{ bot.first_name || 'Telegram Bot' }}</strong><span>@{{ bot.username || 'no_username' }}</span><small>Bot ID {{ bot.bot_id }} · {{ bot.workspace_name }}</small></div><span class="bot-status" :class="{off:!bot.active}">{{bot.active?'active':'inactive'}}</span><button class="secondary" @click="checkHealth(bot)">{{health[bot.id]?.loading?'Checking…':'Check health'}}</button>
          <div v-if="health[bot.id] && !health[bot.id].loading" class="health" :class="{bad:!health[bot.id].connected}"><template v-if="health[bot.id].connected"><b>Webhook connected</b><span>{{health[bot.id].webhook.url}}</span><small>{{health[bot.id].webhook.pending_update_count}} pending update(s)<template v-if="health[bot.id].webhook.last_error_message"> · Last error: {{health[bot.id].webhook.last_error_message}}</template></small></template><template v-else><b>Connection problem</b><span>{{health[bot.id].error}}</span></template></div>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.tg-settings{max-width:1180px}.tg-grid{display:grid;grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr);gap:18px}.tg-card{background:#fff;border:1px solid #dce6e2;border-radius:14px;padding:22px;box-shadow:0 3px 14px rgba(21,57,43,.04)}.tg-card-head{display:flex;gap:13px;margin-bottom:22px}.tg-card-head h2,.section-head h2{margin:0 0 5px}.tg-card-head p{margin:0;color:#74867e;line-height:1.5;font-size:13px}.tg-icon,.tg-avatar{display:grid;place-items:center;background:#229ed9;color:#fff;font-weight:900}.tg-icon{width:42px;height:42px;border-radius:12px;flex:0 0 auto}.tg-avatar{width:38px;height:38px;border-radius:11px;flex:0 0 auto}.tg-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:13px}.tg-form-grid label{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700}.tg-form-grid label.wide{grid-column:1/-1}.tg-form-grid input{border:1px solid #d2ded9;border-radius:8px;padding:10px 11px;font:inherit}.tg-form-grid small{font-weight:400;color:#82938c}.tg-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:18px}.tg-actions button,.bot-row button{padding:9px 12px;border-radius:8px;font-weight:700;cursor:pointer}.secondary{border:1px solid #d4dfda;background:#fff;color:#29453a}.primary{border:1px solid #168b65;background:#168b65;color:white}.tg-preview{margin-top:16px;padding:12px;border-radius:10px;background:#f1f8f5;display:flex;align-items:center;gap:10px}.tg-preview div{flex:1}.tg-preview strong,.tg-preview b,.tg-preview small{display:block}.tg-preview b{font-size:12px;color:#229ed9;margin-top:2px}.tg-preview small{font-size:10px;color:#788a82;margin-top:2px}.tg-preview i{font-style:normal;color:#18845f;font-size:11px;font-weight:800}.tg-success,.tg-error{padding:10px 12px;border-radius:8px;font-size:12px}.tg-success{background:#eef9f3;color:#16724f}.tg-error{background:#fff0f0;color:#9c2929}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-head .eyebrow{margin:0;color:#229ed9;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}.refresh{border:1px solid #d9e3df;background:#fff;border-radius:8px;padding:7px 10px;cursor:pointer}.empty{padding:32px 10px;text-align:center;color:#7d8f87}.empty strong,.empty span{display:block}.empty span{font-size:12px;margin-top:6px}.bot-row{display:grid;grid-template-columns:auto 1fr auto auto;align-items:center;gap:11px;padding:14px 0;border-top:1px solid #edf1ef}.bot-copy strong,.bot-copy span,.bot-copy small{display:block}.bot-copy span{color:#229ed9;font-size:12px;margin-top:2px}.bot-copy small{color:#899991;font-size:10px;margin-top:3px}.bot-status{padding:4px 7px;border-radius:999px;background:#e9f7f1;color:#177657;font-size:10px;font-weight:800}.bot-status.off{background:#f2f2f2;color:#777}.health{grid-column:2/-1;padding:10px 12px;border-radius:8px;background:#edf8f4;color:#4d6e62}.health.bad{background:#fff0f0;color:#8d3535}.health b,.health span,.health small{display:block}.health span{font-size:11px;word-break:break-all;margin:3px 0}.health small{font-size:10px}@media(max-width:950px){.tg-grid{grid-template-columns:1fr}}@media(max-width:620px){.tg-form-grid{grid-template-columns:1fr}.tg-form-grid label.wide{grid-column:auto}.bot-row{grid-template-columns:auto 1fr}.bot-row>.bot-status,.bot-row>button{grid-column:auto}.health{grid-column:1/-1}}
</style>
