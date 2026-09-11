import { createApp } from 'vue'
import Root from './Root.vue'
import './style.css'
import './inbox-layout.css'
import './auth.css'
import './http-response-mapping.css'
import './campaign-question-modal.css'
import './user-details-editor.css'
import './telegram-assignment-ui.css'
import './telegram-inbox-parity.css'
import './live-chat-emoji.css'
import { installLiveChatDisplay } from './live-chat-display'
import { installLiveChatExtras } from './live-chat-extras'
import { installTelegramContactExtras } from './telegram-contact-extras'
import { installLiveChatPagination } from './live-chat-pagination'
import { installFlowTriggerExtras } from './flow-trigger-extras'
import { installTelegramCommands } from './telegram-commands-mount'
import { installSettingsUsersMount } from './settings-users-mount'
import { installUserDetailsEditor } from './user-details-editor'
import { installAgentChatVisibility } from './agent-chat-visibility'
import { installTelegramAssignmentUi } from './telegram-assignment-ui'
import { installTelegramInboxControls } from './telegram-inbox-controls'
import { installLiveChatEmoji } from './live-chat-emoji'

installLiveChatDisplay()
createApp(Root).mount('#app')
installLiveChatExtras()
installTelegramContactExtras()
installLiveChatPagination()
installFlowTriggerExtras()
installTelegramCommands()
installSettingsUsersMount()
installUserDetailsEditor()
installAgentChatVisibility()
installTelegramAssignmentUi()
installTelegramInboxControls()
installLiveChatEmoji()
