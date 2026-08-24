<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  expiresAt: { type: String, default: null },
  compact: { type: Boolean, default: false },
})

const now = ref(Date.now())
let timer = null

const remainingMs = computed(() => props.expiresAt ? Math.max(0, new Date(props.expiresAt).getTime() - now.value) : 0)
const open = computed(() => remainingMs.value > 0)
const label = computed(() => {
  if (!props.expiresAt) return 'No service window'
  if (!open.value) return 'Window expired'
  const totalMinutes = Math.ceil(remainingMs.value / 60000)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours > 0) return compactLabel(hours, minutes)
  return `${minutes}m remaining`
})

function compactLabel(hours, minutes) {
  return `${hours}h ${minutes}m remaining`
}

onMounted(() => { timer = window.setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>

<template>
  <span class="service-window" :class="{ open, expired: !open, compact }" :title="expiresAt ? `Free-form window expires ${new Date(expiresAt).toLocaleString()}` : 'No inbound customer message has opened the service window yet.'">
    <span class="dot"></span>{{ label }}
  </span>
</template>

<style scoped>
.service-window{display:inline-flex;align-items:center;gap:6px;border:1px solid #d8dfdb;border-radius:999px;padding:6px 10px;background:#f8faf9;color:#647169;font-size:11px;font-weight:700;white-space:nowrap}.service-window.open{border-color:#bfe6ce;background:#eefaf2;color:#207344}.service-window.expired{border-color:#ead5d5;background:#fff6f6;color:#9b3b3b}.service-window.compact{padding:4px 8px;font-size:10px}.dot{width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.85}
</style>
