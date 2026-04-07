import { w as writable } from "./index.js";
let nextToastId = 0;
function createToastStore() {
  const { subscribe, update } = writable([]);
  function addToast(type, message, duration = 4e3) {
    const id = nextToastId++;
    update((toasts2) => [...toasts2, { id, type, message }]);
    setTimeout(() => removeToast(id), duration);
  }
  function removeToast(id) {
    update((toasts2) => toasts2.filter((t) => t.id !== id));
  }
  return { subscribe, addToast, removeToast };
}
const toasts = createToastStore();
function createThemeStore() {
  const stored = typeof window !== "undefined" ? localStorage.getItem("theme") : null;
  const initial = stored || "dark";
  const { subscribe, set, update } = writable(initial);
  function applyTheme(theme2) {
    if (typeof document === "undefined") return;
    const isDark = theme2 === "dark" || theme2 === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.classList.toggle("light", !isDark);
  }
  subscribe((value) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("theme", value);
      applyTheme(value);
    }
  });
  function cycle() {
    update((current) => {
      const order = ["dark", "light", "auto"];
      const idx = order.indexOf(current);
      return order[(idx + 1) % order.length];
    });
  }
  if (typeof window !== "undefined") {
    applyTheme(initial);
  }
  return { subscribe, set, cycle };
}
const theme = createThemeStore();
export {
  toasts as a,
  theme as t
};
