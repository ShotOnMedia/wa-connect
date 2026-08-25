import { createApp } from 'vue'
import Root from './Root.vue'
import './style.css'
import './inbox-layout.css'
import './auth.css'
import { installLiveChatExtras } from './live-chat-extras'

createApp(Root).mount('#app')
installLiveChatExtras()
