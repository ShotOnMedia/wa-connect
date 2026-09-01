<script setup>
import { computed } from 'vue'

const props=defineProps({
  value:{type:String,default:''},
  latitude:{type:[String,Number],default:null},
  longitude:{type:[String,Number],default:null},
  height:{type:Number,default:190}
})

function parseCoordinatePair(value){
  const match=String(value||'').trim().match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/)
  if(!match)return null
  const lat=Number(match[1]),lng=Number(match[2])
  if(!Number.isFinite(lat)||!Number.isFinite(lng)||lat < -90||lat > 90||lng < -180||lng > 180)return null
  return {lat,lng}
}

const coords=computed(()=>{
  if(props.latitude!==null&&props.longitude!==null&&props.latitude!==''&&props.longitude!==''){
    const lat=Number(props.latitude),lng=Number(props.longitude)
    if(Number.isFinite(lat)&&Number.isFinite(lng)&&lat>=-90&&lat<=90&&lng>=-180&&lng<=180)return {lat,lng}
  }
  return parseCoordinatePair(props.value)
})
const formatted=computed(()=>coords.value?`${coords.value.lat}, ${coords.value.lng}`:String(props.value||''))
const embedUrl=computed(()=>{
  if(!coords.value)return ''
  const {lat,lng}=coords.value,delta=.008
  const bbox=[lng-delta,lat-delta,lng+delta,lat+delta].join(',')
  return `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${encodeURIComponent(`${lat},${lng}`)}`
})
const openUrl=computed(()=>coords.value?`https://www.openstreetmap.org/?mlat=${coords.value.lat}&mlon=${coords.value.lng}#map=16/${coords.value.lat}/${coords.value.lng}`:'')
</script>

<template>
  <div class="location-preview">
    <iframe v-if="coords" :src="embedUrl" :style="{height:`${height}px`}" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="Shared location on OpenStreetMap"></iframe>
    <div class="location-footer">
      <span>{{formatted}}</span>
      <a v-if="coords" :href="openUrl" target="_blank" rel="noopener noreferrer">Open map ↗</a>
    </div>
    <small v-if="coords">© OpenStreetMap contributors</small>
  </div>
</template>

<style scoped>
.location-preview{width:min(360px,100%);overflow:hidden;border:1px solid #dce5e1;border-radius:9px;background:#fff}.location-preview iframe{display:block;width:100%;border:0;background:#eef3f1}.location-footer{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:9px 10px 4px}.location-footer span{font-size:12px;color:#31453c;white-space:nowrap}.location-footer a{font-size:11px;font-weight:700;color:#1678a5;text-decoration:none;white-space:nowrap}.location-footer a:hover{text-decoration:underline}.location-preview small{display:block;padding:0 10px 8px;color:#8a9891;font-size:8px}@media(max-width:520px){.location-footer{align-items:flex-start;flex-direction:column;gap:4px}.location-footer span{white-space:normal}}
</style>