import { createApp, h, Fragment } from 'vue'
import LoginDialog from './LoginDialog.vue'
import BookDetails from './BookDetails.vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

createApp({ render: () => h(Fragment, [h(LoginDialog), h(BookDetails)]) }).mount('#login-ui')
