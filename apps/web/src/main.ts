import { createApp } from "vue";
import { createPinia } from "pinia";

import "@fontsource/outfit/400.css";
import "@fontsource/outfit/500.css";
import "@fontsource/outfit/600.css";
import "@fontsource/outfit/700.css";
import "overlayscrollbars/overlayscrollbars.css";
import App from "./App.vue";
import { router } from "./router";
import "./styles.css";

createApp(App).use(createPinia()).use(router).mount("#app");
