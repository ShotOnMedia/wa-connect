import { createApp } from 'vue'
import Root from './Root.vue'
import './style.css'
import './inbox-layout.css'
import './auth.css'
import './http-response-mapping.css'
import './campaign-question-modal.css'
import { installLiveChatExtras } from './live-chat-extras'
import { installTelegramContactExtras } from './telegram-contact-extras'

createApp(Root).mount('#app')
installLiveChatExtras()
installTelegramContactExtras()
