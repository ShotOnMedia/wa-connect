<script setup>
import { onBeforeUnmount,onMounted } from 'vue'
import { api } from './api'
import FlowBuilder from './FlowBuilder.vue'
const props=defineProps({currentUser:{type:Object,required:true}})
onMounted(()=>api.setFlowChannel('telegram'))
onBeforeUnmount(()=>api.setFlowChannel('whatsapp'))
</script>

<template>
  <section class="telegram-flows">
    <div class="channel-notice">
      <span class="telegram-icon">T</span>
      <div>
        <strong>Telegram automation workspace</strong>
        <small>Flows use the shared WA Connect visual builder and are now stored separately from WhatsApp flows.</small>
      </div>
      <span class="shared-pill">Telegram runtime active</span>
    </div>
    <FlowBuilder :current-user="currentUser" channel="telegram" />
  </section>
</template>

<style scoped>
.telegram-flows{margin:-4px -38px -34px}.channel-notice{margin:0 38px 10px;display:flex;align-items:center;gap:11px;padding:11px 14px;border:1px solid #cfe6f0;border-radius:11px;background:#f1f9fc}.telegram-icon{width:31px;height:31px;border-radius:9px;background:#229ed9;color:#fff;display:grid;place-items:center;font-weight:900}.channel-notice div{flex:1}.channel-notice strong,.channel-notice small{display:block}.channel-notice strong{font-size:12px;color:#17372b}.channel-notice small{margin-top:2px;color:#72877e;font-size:10px}.shared-pill{padding:5px 8px;border-radius:999px;background:#dff2fa;color:#147fae;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.04em}@media(max-width:750px){.channel-notice{align-items:flex-start;flex-wrap:wrap}.shared-pill{margin-left:42px}}
</style>