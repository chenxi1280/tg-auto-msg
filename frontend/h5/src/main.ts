import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/styles/global.scss'
import { useUserStore } from './stores/user'

const app = createApp(App)

// 使用 Pinia
const pinia = createPinia()
app.use(pinia)

// 使用 Vue Router
app.use(router)

// 恢复用户登录状态
const userStore = useUserStore()
userStore.restoreUser()

app.mount('#app')
