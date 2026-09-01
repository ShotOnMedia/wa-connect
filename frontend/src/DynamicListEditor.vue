<script setup>
defineProps({draft:{type:Object,required:true},fields:{type:Array,default:()=>[]}})
</script>

<template>
  <section class="dynamic-list">
    <div class="intro">
      <strong>List row generation</strong>
      <p>Use this Button as either one static list row or as a template that expands JSON from a subscriber field into dynamic rows.</p>
    </div>
    <label>Row generation
      <select v-model="draft.row_generation">
        <option value="static">Static row</option>
        <option value="dynamic">Dynamic rows from JSON</option>
      </select>
    </label>
    <template v-if="draft.row_generation==='dynamic'">
      <label>JSON source field
        <select v-model="draft.dynamic_source_field_id">
          <option value="">— Select custom field —</option>
          <option v-for="f in fields" :key="f.id" :value="f.id">{{f.label || f.name || f.key}} · %{{f.key}}%</option>
        </select>
      </label>
      <label>Array path <small>Optional. Leave blank if the field itself contains the array.</small>
        <input v-model="draft.dynamic_array_path" placeholder="e.g. products or data.items">
      </label>
      <div class="grid">
        <label>Row title key
          <input v-model="draft.dynamic_title_path" placeholder="product_name">
        </label>
        <label>Saved value key
          <input v-model="draft.dynamic_value_path" placeholder="id or buy_link">
        </label>
      </div>
      <label>Row description
        <input v-model="draft.dynamic_description" placeholder="{{item.price}} · {{item.description}}">
        <small>Use {{item.key}} placeholders from each JSON item.</small>
      </label>
      <label>Save selection to
        <select v-model="draft.dynamic_save_field_id">
          <option value="">— Do not save —</option>
          <option v-for="f in fields" :key="f.id" :value="f.id">{{f.label || f.name || f.key}} · %{{f.key}}%</option>
        </select>
      </label>
      <label class="check"><input v-model="draft.dynamic_save_entire_object" type="checkbox"> Save the entire selected JSON object instead of the value key</label>
      <div class="example">
        <b>Example</b>
        <code>[{"id":123,"product_name":"Widget A","price":"R299"}]</code>
        <span>Title: <code>product_name</code> · Description: <code>{{'{{item.price}}'}}</code> · Value: <code>id</code></span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.dynamic-list{border:1px solid #dbe7e2;border-radius:12px;padding:14px;margin:14px 0;background:#f9fcfb}.intro{margin-bottom:12px}.intro p{font-size:12px;color:#6b7d76;margin:4px 0 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.dynamic-list small{font-weight:400;color:#71817b}.check{flex-direction:row!important;align-items:center}.check input{width:auto}.example{background:#eef8f3;border-radius:8px;padding:10px;font-size:11px;display:flex;flex-direction:column;gap:5px}.example code{white-space:normal;word-break:break-word}@media(max-width:520px){.grid{grid-template-columns:1fr}}
</style>
