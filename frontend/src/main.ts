import { createApp } from 'vue'
import { Quasar } from 'quasar'
import pl from 'quasar/lang/pl'
import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
import './style.css'
import App from './App.vue'
import router from './router'
import { getThemePreference } from './theme'

createApp(App)
  .use(Quasar, {
    lang: pl,
    config: { dark: getThemePreference() },
  })
  .use(router)
  .mount('#app')
