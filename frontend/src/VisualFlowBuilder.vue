<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from './api'

const props = defineProps({ currentUser:{type:Object,required:true} })
const flows=ref([]), selected=ref(null), graph=ref({nodes:[],edges:[]}), selectedNodeId=ref(null)
const loading=ref(false), saving=ref(false), error=ref(''), success=ref(''), connectFrom=ref(null)
const canvas=ref(null), search=ref('')
const createForm=reactive({name:'',trigger_type:'manual',trigger_value:''})
const nodeDraft=reactive({title:'',text:'',seconds:60,condition_field:'service_window',operator:'open',value:''})

const groups=[
 {label:'Messages',items:[['send_message','Text','💬'],['image','Image','🖼'],['video','Video','🎥'],['audio','Audio','🎵'],['file','File','📎']]},
 {label:'Interactive',items:[['question','Question','❓'],['interactive','Interactive message','🔘'],['template','Template message','🧩']]},
 {label:'Contact',items:[['add_tag','Add tag','🏷'],['remove_tag','Remove tag','✂'],['set_field','Set custom field','📝'],['assign_user','Assign agent','👤']]},
 {label:'Flow control',items:[['condition','Condition','⑂'],['delay','Delay','⏱'],['set_status','Conversation status','✓']]},
 {label:'Integrations',items:[['http_request','HTTP request','🌐']]},
]
const filteredGroups=computed(()=>groups.map(g=>({...g,items:g.items.filter(i=>i[1].toLowerCase().includes(search.value.toLowerCase()))})).filter(g=>g.items.length))
const selectedNode=computed(()=>graph.value.nodes.find(n=>n.id===selectedNodeId.value)||null)
const nodeWidth=240,nodeHeight=104

function labelFor(type){return groups.flatMap(g=>g.items).find(i=>i[0]===type)?.[1]|| (type==='trigger'?'Start':'Block')}
function iconFor(type){return groups.flatMap(g=>g.items).find(i=>i[0]===type)?.[2]||'⚡'}
function summary(n){const c=n.config||{};if(n.node_type==='trigger')return c.trigger_value||c.trigger_type||'Manual';if(n.node_type==='send_message')return c.text||'Configure message';if(n.node_type==='condition')return `${c.field||'service_window'} ${c.operator||'open'} ${c.value||''}`.trim();if(n.node_type==='delay')return `${c.seconds||60}s`;return n.title||'Configure block'}
function nodeById(id){return graph.value.nodes.find(n=>n.id===id)}
function edgePath(e){const s=nodeById(e.source_node_id),t=nodeById(e.target_node_id);if(!s||!t)return'';const sx=s.position_x+nodeWidth,sy=s.position_y+(e.source_handle==='yes'?70:e.source_handle==='no'?88:52),tx=t.position_x,ty=t.position_y+52;const dx=Math.max(70,(tx-sx)/2);return `M ${sx} ${sy} C ${sx+dx} ${sy}, ${tx-dx} ${ty}, ${tx} ${ty}`}

async function loadFlows(auto=true){loading.value=true;try{flows.value=await api.flows();if(auto&&!selected.value&&flows.value.length)await selectFlow(flows.value[0])}catch(e){error.value=e.message}finally{loading.value=false}}
async function createFlow(){saving.value=true;error.value='';try{const f=await api.createFlow({name:createForm.name,trigger_type:createForm.trigger_type,trigger_value:createForm.trigger_type==='keyword'?createForm.trigger_value:null,stop_on_reply:false});createForm.name='';createForm.trigger_value='';await loadFlows(false);await selectFlow(f)}catch(e){error.value=e.message}finally{saving.value=false}}
async function selectFlow(flow){selected.value=await api.flow(flow.id||flow);graph.value=await api.flowGraph(selected.value.id);selectedNodeId.value=null;connectFrom.value=null;if(!graph.value.nodes.length)await seedGraph()}
async function seedGraph(){if(!selected.value)return;let x=80,y=80;const trigger=await api.addFlowNode(selected.value.id,{node_type:'trigger',title:'Start',config:{trigger_type:selected.value.trigger_type,trigger_value:selected.value.trigger_value},position_x:x,position_y:y});graph.value.nodes.push(trigger);let prev=trigger;y+=150;for(const step of selected.value.steps||[]){const node=await api.addFlowNode(selected.value.id,{node_type:step.step_type,title:null,config:step.config||{},position_x:x+300,position_y:y});graph.value.nodes.push(node);const edge=await api.addFlowEdge(selected.value.id,{source_node_id:prev.id,source_handle:'next',target_node_id:node.id,target_handle:'input'});graph.value.edges.push(edge);prev=node;y+=150}success.value='Visual graph created from the existing flow.'}
async function addNode(type){if(!selected.value)return;const count=graph.value.nodes.length;const node=await api.addFlowNode(selected.value.id,{node_type:type,title:labelFor(type),config:type==='delay'?{seconds:60}:type==='condition'?{field:'service_window',operator:'open',value:''}:{},position_x:360+(count%3)*280,position_y:90+Math.floor(count/3)*170});graph.value.nodes.push(node);selectedNodeId.value=node.id;hydrateDraft(node)}
function hydrateDraft(n){const c=n?.config||{};nodeDraft.title=n?.title||'';nodeDraft.text=c.text||'';nodeDraft.seconds=c.seconds||60;nodeDraft.condition_field=c.field||'service_window';nodeDraft.operator=c.operator||'open';nodeDraft.value=c.value||''}
function selectNode(n){selectedNodeId.value=n.id;hydrateDraft(n)}
async function saveNode(){const n=selectedNode.value;if(!n)return;let config={...(n.config||{})};if(n.node_type==='send_message')config.text=nodeDraft.text;if(n.node_type==='delay')config.seconds=Number(nodeDraft.seconds);if(n.node_type==='condition')config={field:nodeDraft.condition_field,operator:nodeDraft.operator,value:nodeDraft.value};const updated=await api.updateFlowNode(selected.value.id,n.id,{title:nodeDraft.title||null,config});const i=graph.value.nodes.findIndex(x=>x.id===n.id);graph.value.nodes[i]=updated;success.value='Block saved.'}
async function deleteNode(n){if(n.node_type==='trigger'||!confirm('Delete this block and its connections?'))return;await api.deleteFlowNode(selected.value.id,n.id);graph.value.nodes=graph.value.nodes.filter(x=>x.id!==n.id);graph.value.edges=graph.value.edges.filter(e=>e.source_node_id!==n.id&&e.target_node_id!==n.id);selectedNodeId.value=null}
async function dragEnd(ev,n){const r=canvas.value.getBoundingClientRect();const x=Math.max(20,Math.round(ev.clientX-r.left-30+canvas.value.scrollLeft));const y=Math.max(20,Math.round(ev.clientY-r.top-20+canvas.value.scrollTop));n.position_x=x;n.position_y=y;await api.updateFlowNode(selected.value.id,n.id,{position_x:x,position_y:y})}
function armConnection(n,handle='next'){connectFrom.value={node_id:n.id,handle}}
async function connectTo(n){if(!connectFrom.value||connectFrom.value.node_id===n.id)return;try{const edge=await api.addFlowEdge(selected.value.id,{source_node_id:connectFrom.value.node_id,source_handle:connectFrom.value.handle,target_node_id:n.id,target_handle:'input'});graph.value.edges.push(edge);connectFrom.value=null}catch(e){error.value=e.message}}
async function deleteEdge(e){await api.deleteFlowEdge(selected.value.id,e.id);graph.value.edges=graph.value.edges.filter(x=>x.id!==e.id)}
async function updateStatus(status){selected.value=await api.updateFlow(selected.value.id,{status});await loadFlows(false)}

onMounted(()=>loadFlows())
</script>

<template>
<section class="visual-builder">
  <aside class="blocks-panel">
    <div class="blocks-head"><div><b>Flow blocks</b><small>Click a block to add it</small></div></div>
    <input v-model="search" class="block-search" placeholder="Search blocks…"/>
    <div class="block-groups"><section v-for="g in filteredGroups" :key="g.label"><h4>{{g.label}}</h4><button v-for="item in g.items" :key="item[0]" @click="addNode(item[0])"><span>{{item[2]}}</span>{{item[1]}}</button></section></div>
  </aside>

  <div class="builder-main">
    <header class="builder-toolbar">
      <div class="flow-picker"><select v-if="flows.length" :value="selected?.id||''" @change="selectFlow(Number($event.target.value))"><option v-for="f in flows" :key="f.id" :value="f.id">{{f.name}}</option></select><form @submit.prevent="createFlow"><input v-model="createForm.name" required placeholder="New flow…"/><select v-model="createForm.trigger_type"><option value="manual">Manual</option><option value="keyword">Keyword</option><option value="first_message">First message</option></select><input v-if="createForm.trigger_type==='keyword'" v-model="createForm.trigger_value" required placeholder="Keyword"/><button>Create</button></form></div>
      <div v-if="selected" class="toolbar-actions"><span :class="['flow-state',selected.status]">{{selected.status}}</span><select :value="selected.status" @change="updateStatus($event.target.value)"><option value="draft">Draft</option><option value="active">Active</option><option value="paused">Paused</option></select></div>
    </header>

    <div v-if="selected" ref="canvas" class="flow-stage" @click.self="connectFrom=null">
      <svg class="edge-layer"><path v-for="e in graph.edges" :key="e.id" :d="edgePath(e)" @dblclick="deleteEdge(e)"/></svg>
      <article v-for="n in graph.nodes" :key="n.id" class="graph-node" :class="[n.node_type,{selected:selectedNodeId===n.id}]" :style="{left:n.position_x+'px',top:n.position_y+'px'}" draggable="true" @dragend="dragEnd($event,n)" @click.stop="selectNode(n)">
        <header><span>{{iconFor(n.node_type)}}</span><strong>{{n.title||labelFor(n.node_type)}}</strong><button v-if="n.node_type!=='trigger'" @click.stop="deleteNode(n)">×</button></header>
        <p>{{summary(n)}}</p>
        <button class="input-port" title="Connect here" @click.stop="connectTo(n)"></button>
        <template v-if="n.node_type==='condition'"><button class="output-port yes" title="Yes path" @click.stop="armConnection(n,'yes')"><i>YES</i></button><button class="output-port no" title="No path" @click.stop="armConnection(n,'no')"><i>NO</i></button></template>
        <button v-else class="output-port" title="Next" @click.stop="armConnection(n,'next')"></button>
      </article>
      <div v-if="connectFrom" class="connect-hint">Select the input dot on the next block · Esc/click canvas to cancel</div>
    </div>
    <div v-else class="empty-canvas">Create a flow to start building.</div>
  </div>

  <aside v-if="selectedNode" class="properties-panel">
    <div class="properties-head"><div><small>Block settings</small><h3>{{labelFor(selectedNode.node_type)}}</h3></div><button @click="selectedNodeId=null">×</button></div>
    <label>Title<input v-model="nodeDraft.title"/></label>
    <label v-if="selectedNode.node_type==='send_message'">Message<textarea v-model="nodeDraft.text" rows="6" placeholder="Message to send…"/></label>
    <label v-if="selectedNode.node_type==='delay'">Seconds<input v-model.number="nodeDraft.seconds" type="number" min="1"/></label>
    <template v-if="selectedNode.node_type==='condition'"><label>Check<select v-model="nodeDraft.condition_field"><option value="service_window">24-hour service window</option><option value="tag">Contact tag</option><option value="custom_field">Custom field</option><option value="conversation_status">Conversation status</option><option value="assigned_user">Assigned agent</option></select></label><label>Operator<select v-model="nodeDraft.operator"><option value="open">Open / is</option><option value="closed">Closed / is not</option><option value="equals">Equals</option><option value="not_equals">Not equals</option><option value="contains">Contains</option><option value="empty">Empty</option><option value="not_empty">Not empty</option></select></label><label>Value<input v-model="nodeDraft.value"/></label></template>
    <button class="save-block" @click="saveNode">Save block</button>
    <p class="property-help">Drag cards on the canvas. Click an output dot, then the input dot of another block to connect them. Double-click a connector line to remove it.</p>
  </aside>

  <p v-if="error" class="builder-toast error">{{error}}</p><p v-if="success" class="builder-toast">{{success}}</p>
</section>
</template>

<style scoped>
.visual-builder{height:100vh;display:grid;grid-template-columns:250px 1fr;position:relative;background:#eef4f7;color:#17352a}.visual-builder:has(.properties-panel){grid-template-columns:250px 1fr 300px}.blocks-panel,.properties-panel{background:#fff;border-right:1px solid #dce5e8;overflow:auto;z-index:4}.properties-panel{border-right:0;border-left:1px solid #dce5e8;padding:18px}.blocks-head,.properties-head{padding:18px;border-bottom:1px solid #edf1f3;display:flex;justify-content:space-between}.blocks-head b,.blocks-head small{display:block}.blocks-head small{color:#7e9098;margin-top:3px}.block-search{margin:14px;width:calc(100% - 28px);padding:10px;border:1px solid #d9e2e5;border-radius:9px}.block-groups section{padding:0 12px 13px}.block-groups h4{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:#91a2aa;margin:8px 0}.block-groups button{width:100%;display:flex;gap:9px;align-items:center;padding:10px;border:0;border-bottom:1px solid #edf2f3;background:#fff;text-align:left;color:#29463c;cursor:pointer}.block-groups button:hover{background:#f4faf7}.builder-main{min-width:0;display:flex;flex-direction:column}.builder-toolbar{height:72px;background:rgba(255,255,255,.94);border-bottom:1px solid #dce5e8;padding:12px 18px;display:flex;justify-content:space-between;align-items:center;z-index:3}.flow-picker,.flow-picker form,.toolbar-actions{display:flex;gap:8px;align-items:center}.builder-toolbar input,.builder-toolbar select{padding:9px;border:1px solid #d5dfe2;border-radius:8px;background:#fff}.builder-toolbar button,.save-block{border:0;border-radius:8px;background:#16ad63;color:#fff;padding:10px 14px;font-weight:700}.flow-state{text-transform:uppercase;font-size:9px;padding:6px 9px;border-radius:999px;background:#edf1ef}.flow-state.active{background:#e5f8ec;color:#167648}.flow-stage{position:relative;flex:1;overflow:auto;min-height:700px;background-image:radial-gradient(#c9d6db 1px,transparent 1px);background-size:24px 24px}.edge-layer{position:absolute;inset:0;width:2200px;height:1500px;pointer-events:none;overflow:visible}.edge-layer path{fill:none;stroke:#607985;stroke-width:2.2;pointer-events:stroke;cursor:pointer}.graph-node{position:absolute;width:240px;min-height:104px;background:#fff;border:1px solid #dbe5e7;border-radius:12px;box-shadow:0 8px 22px rgba(46,72,82,.11);cursor:grab;z-index:2}.graph-node.selected{outline:2px solid #1fc875}.graph-node header{display:flex;align-items:center;gap:7px;padding:11px 12px;border-bottom:1px solid #edf2f3}.graph-node header strong{flex:1}.graph-node header button{border:0;background:none;color:#a44;font-size:18px}.graph-node p{margin:0;padding:12px;color:#6c7f78;font-size:12px;min-height:42px}.input-port,.output-port{position:absolute;width:14px;height:14px;border-radius:50%;border:2px solid #fff;background:#607985;box-shadow:0 0 0 1px #607985;padding:0}.input-port{left:-8px;top:45px}.output-port{right:-8px;top:45px}.output-port.yes{top:64px;background:#1dab62}.output-port.no{top:84px;background:#d86161}.output-port i{position:absolute;right:16px;top:-3px;font-style:normal;font-size:8px;color:#607985;font-weight:800}.connect-hint{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#17352a;color:#fff;padding:10px 15px;border-radius:999px;z-index:8}.empty-canvas{display:grid;place-items:center;flex:1;color:#819198}.properties-head{padding:0 0 14px;margin-bottom:15px}.properties-head small{color:#1a9a5d;text-transform:uppercase;font-weight:800}.properties-head h3{margin:3px 0}.properties-head button{border:0;background:none;font-size:22px}.properties-panel label{display:grid;gap:6px;font-size:12px;font-weight:700;margin:12px 0}.properties-panel input,.properties-panel select,.properties-panel textarea{padding:10px;border:1px solid #d6e0e2;border-radius:8px;font:inherit}.save-block{width:100%;margin-top:8px}.property-help{font-size:11px;color:#82928b;line-height:1.5}.builder-toast{position:fixed;right:24px;bottom:24px;background:#e8f8ee;color:#167648;padding:10px 14px;border-radius:9px;z-index:10}.builder-toast.error{background:#fff0f0;color:#a93636}@media(max-width:1000px){.visual-builder,.visual-builder:has(.properties-panel){grid-template-columns:210px 1fr}.properties-panel{position:fixed;right:0;top:0;bottom:0;width:290px;z-index:10;box-shadow:-12px 0 30px rgba(0,0,0,.08)}}
</style>
