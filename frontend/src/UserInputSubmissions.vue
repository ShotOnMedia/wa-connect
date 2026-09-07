<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from './api'

const props = defineProps({ channel: { type: String, default: 'whatsapp' } })

const submissions = ref([])
const loading = ref(false)
const error = ref('')
const search = ref('')
const status = ref('all')
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref(null)

const channelName = computed(() => props.channel === 'telegram' ? 'Telegram' : 'WhatsApp')
const filtered = computed(() => submissions.value.filter((row) => {
  const q = search.value.trim().toLowerCase()
  const matchesSearch = !q || [row.id, row.flow_name, row.campaign_name, row.contact_id, row.conversation_id]
    .some((v) => String(v ?? '').toLowerCase().includes(q))
  const matchesStatus = status.value === 'all' || row.status === status.value
  return matchesSearch && matchesStatus
}))

function fmt(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
  }).format(new Date(value))
}

function statusLabel(value) {
  return String(value || 'unknown').replaceAll('_', ' ')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const rows = await api.userInputSubmissions(null, 250)
    submissions.value = rows.filter((row) => row.channel === props.channel)
  } catch (e) {
    error.value = e.message || 'Could not load submissions'
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  detailOpen.value = true
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    detail.value = await api.userInputSubmission(row.id)
  } catch (e) {
    detailError.value = e.message || 'Could not load submission'
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
  detail.value = null
  detailError.value = ''
}

watch(() => props.channel, load)
onMounted(load)
</script>

<template>
  <section class="submissions-page">
    <header class="submissions-head">
      <div>
        <p class="eyebrow">{{ channelName }} automation</p>
        <h1>Submissions</h1>
        <p>Inspect answers collected by User Input blocks.</p>
      </div>
      <button class="refresh" @click="load">↻ Refresh</button>
    </header>

    <div class="submissions-card">
      <div class="tools">
        <input v-model="search" placeholder="Search flow, contact, conversation or ID…" />
        <select v-model="status">
          <option value="all">All statuses</option>
          <option value="in_progress">In progress</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="error">Error</option>
        </select>
      </div>

      <div v-if="error" class="error-box">{{ error }}</div>
      <div v-if="loading" class="empty">Loading submissions…</div>
      <div v-else-if="!filtered.length" class="empty">
        <strong>No submissions found</strong>
        <span>Complete a User Input flow or change the filters above.</span>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr><th>ID</th><th>Flow / Campaign</th><th>Status</th><th>Contact</th><th>Started</th><th>Completed</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="row in filtered" :key="row.id" @click="openDetail(row)">
              <td><code>#{{ row.id }}</code></td>
              <td><strong>{{ row.flow_name || `Flow #${row.flow_id}` }}</strong><small>{{ row.campaign_name || `Node #${row.campaign_node_id}` }}</small></td>
              <td><span :class="['status-pill', row.status]">{{ statusLabel(row.status) }}</span></td>
              <td><strong>#{{ row.contact_id }}</strong><small>Conversation #{{ row.conversation_id }}</small></td>
              <td>{{ fmt(row.started_at) }}</td>
              <td>{{ fmt(row.completed_at) }}</td>
              <td><button class="view-button" @click.stop="openDetail(row)">View →</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer>{{ filtered.length }} of {{ submissions.length }} submissions</footer>
    </div>
  </section>

  <div v-if="detailOpen" class="modal-backdrop" @click.self="closeDetail">
    <section class="detail-modal">
      <header>
        <div>
          <p class="eyebrow">Submission detail</p>
          <h2>{{ detail?.campaign_name || detail?.flow_name || 'Submission' }} <small v-if="detail">#{{ detail.id }}</small></h2>
        </div>
        <button class="close" @click="closeDetail">×</button>
      </header>

      <div v-if="detailError" class="error-box">{{ detailError }}</div>
      <div v-if="detailLoading" class="empty">Loading submission…</div>
      <template v-else-if="detail">
        <div class="summary-grid">
          <article><span>Channel</span><strong>{{ channelName }}</strong></article>
          <article><span>Status</span><strong>{{ statusLabel(detail.status) }}</strong></article>
          <article><span>Contact</span><strong>#{{ detail.contact_id }}</strong></article>
          <article><span>Conversation</span><strong>#{{ detail.conversation_id }}</strong></article>
          <article><span>Started</span><strong>{{ fmt(detail.started_at) }}</strong></article>
          <article><span>Completed</span><strong>{{ fmt(detail.completed_at) }}</strong></article>
        </div>

        <section class="answers-section">
          <header><h3>Collected answers</h3><span>{{ detail.answers?.length || 0 }} answer{{ detail.answers?.length === 1 ? '' : 's' }}</span></header>
          <div v-if="!detail.answers?.length" class="empty answers-empty">No answers recorded yet.</div>
          <div v-else class="answers-list">
            <article v-for="answer in detail.answers" :key="answer.id">
              <div class="answer-head">
                <div><strong>{{ answer.question_text || answer.answer_key }}</strong><code>%input.{{ answer.answer_key }}%</code></div>
                <small>{{ fmt(answer.created_at) }}</small>
              </div>
              <p>{{ answer.value || '—' }}</p>
            </article>
          </div>
        </section>

        <section class="webhook-section">
          <h3>Webhook</h3>
          <div v-if="detail.webhook_url"><span>Destination</span><code>{{ detail.webhook_url }}</code></div>
          <p v-else>No webhook destination configured for this submission.</p>
        </section>
      </template>
    </section>
  </div>
</template>

<style scoped>
.submissions-page{width:min(1220px,calc(100% - 64px));margin:0 auto;padding:34px 0 60px}.submissions-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}.submissions-head h1{margin:2px 0 8px;font-size:30px}.submissions-head p:last-child{margin:0;color:#7b8b83}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:11px!important;font-weight:800;color:#07934d!important;margin:0}.refresh{border:1px solid #d6e0da;border-radius:9px;background:#fff;padding:10px 14px;cursor:pointer}.submissions-card{background:#fff;border:1px solid #dce5df;border-radius:16px;box-shadow:0 12px 30px rgba(20,55,40,.05);overflow:hidden}.tools{display:flex;gap:10px;padding:18px;border-bottom:1px solid #e8eeea}.tools input,.tools select{border:1px solid #d6e0da;border-radius:9px;padding:10px 12px;background:#fff}.tools input{flex:1}.tools select{min-width:180px}.table-wrap{overflow:auto}.table-wrap table{width:100%;border-collapse:collapse;min-width:980px}.table-wrap th{padding:12px 18px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#829188;background:#f7faf8;border-bottom:1px solid #e5ece8}.table-wrap td{padding:15px 18px;border-bottom:1px solid #edf1ef;vertical-align:middle}.table-wrap tbody tr{cursor:pointer}.table-wrap tbody tr:hover{background:#f9fcfa}.table-wrap td strong,.table-wrap td small{display:block}.table-wrap td small{color:#89968f;margin-top:3px}.table-wrap code{font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1f5f3;color:#5c6d64;border-radius:6px;padding:4px 7px}.status-pill{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800;text-transform:uppercase}.status-pill.completed{background:#e4f7eb;color:#08763e}.status-pill.in_progress,.status-pill.running{background:#e7f2ff;color:#2766a8}.status-pill.failed,.status-pill.error{background:#fde7e7;color:#a92e2e}.view-button{border:1px solid #d9e3dd;border-radius:8px;background:#fff;padding:7px 10px;cursor:pointer}.submissions-card footer{padding:13px 18px;color:#89968f;font-size:12px;background:#fafcfb}.empty{padding:60px 20px;text-align:center;color:#819087;display:flex;flex-direction:column;gap:6px}.error-box{margin:14px 18px;padding:10px 12px;border-radius:8px;background:#fff0f0;color:#b22}.modal-backdrop{position:fixed;inset:0;z-index:1200;background:rgba(12,30,22,.48);display:grid;place-items:center;padding:24px}.detail-modal{width:min(900px,96vw);max-height:90vh;overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.22)}.detail-modal>header{display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-bottom:1px solid #e5ece8}.detail-modal h2{margin:3px 0 0}.detail-modal h2 small{font-size:12px;color:#7e8c85;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.close{border:0;background:none;font-size:28px;cursor:pointer}.summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:22px 24px}.summary-grid article{border:1px solid #e3e9e6;border-radius:11px;padding:13px}.summary-grid span,.summary-grid strong{display:block}.summary-grid span{color:#829188;font-size:11px;text-transform:uppercase;letter-spacing:.05em}.summary-grid strong{margin-top:6px;font-size:13px}.answers-section,.webhook-section{padding:0 24px 24px}.answers-section>header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.answers-section h3,.webhook-section h3{margin:0;font-size:16px}.answers-section>header span{color:#89968f;font-size:12px}.answers-list{display:flex;flex-direction:column;gap:10px}.answers-list article{border:1px solid #e3e9e6;border-radius:11px;padding:14px}.answer-head{display:flex;justify-content:space-between;gap:20px}.answer-head strong,.answer-head code{display:block}.answer-head code{margin-top:4px;color:#2b6d4e;font:11px ui-monospace,SFMono-Regular,Menlo,monospace}.answer-head small{color:#89968f;white-space:nowrap}.answers-list p{margin:11px 0 0;white-space:pre-wrap;color:#32473d}.answers-empty{padding:24px}.webhook-section>div{margin-top:10px;padding:13px;border-radius:10px;background:#f7faf8}.webhook-section span,.webhook-section code{display:block}.webhook-section span{font-size:11px;color:#819087;text-transform:uppercase}.webhook-section code{margin-top:5px;word-break:break-all}.webhook-section p{color:#7b8b83}@media(max-width:850px){.submissions-page{width:calc(100% - 28px)}.submissions-head{align-items:flex-start;flex-direction:column}.tools{flex-wrap:wrap}.tools input{flex-basis:100%}.summary-grid{grid-template-columns:1fr 1fr}}@media(max-width:560px){.summary-grid{grid-template-columns:1fr}.answer-head{flex-direction:column;gap:5px}}
</style>
