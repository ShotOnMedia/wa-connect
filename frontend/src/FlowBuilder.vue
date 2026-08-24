<script setup>
import VisualFlowBuilder from './VisualFlowBuilder.vue'

defineProps({ currentUser:{type:Object,required:true} })
</script>

<template>
  <VisualFlowBuilder :current-user="currentUser" />
</template>
