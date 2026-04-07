import { a as attr_class, b as attr, s as stringify, e as escape_html, c as ensure_array_like, d as derived, f as clsx } from "../../chunks/index2.js";
import { t as theme, a as toasts } from "../../chunks/stores.js";
function _layout($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let { children } = $$props;
    let currentTheme = "dark";
    theme.subscribe((v) => currentTheme = v);
    const themeIcon = derived(() => currentTheme === "dark" ? "🌙" : currentTheme === "light" ? "☀️" : "🖥️");
    const themeLabel = derived(() => currentTheme === "dark" ? "Dark" : currentTheme === "light" ? "Light" : "Auto");
    let toastList = [];
    toasts.subscribe((v) => toastList = v);
    const navLinkClass = "rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white";
    $$renderer2.push(`<div class="min-h-screen bg-zinc-100 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100"><nav class="sticky top-0 z-50 border-b border-zinc-200 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-900/80"><div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6"><a href="/" class="text-xl font-bold tracking-tight text-zinc-900 dark:text-white">Clipcast</a> <div class="hidden items-center gap-1 sm:flex"><a href="/"${attr_class(clsx(navLinkClass))}>Podcasts</a> <a href="/podcast/add"${attr_class(clsx(navLinkClass))}>Add Podcast</a> <div class="admin-dropdown relative"><button${attr_class(`${stringify(navLinkClass)} inline-flex items-center gap-1`)}>Admin <svg${attr_class(`h-4 w-4 transition-transform ${stringify("")}`)} fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"></path></svg></button> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div> <button class="ml-2 rounded-lg px-3 py-2 text-sm text-zinc-500 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"${attr("title", `Toggle theme (${stringify(themeLabel())})`)}>${escape_html(themeIcon())}</button></div> <div class="flex items-center gap-2 sm:hidden"><button class="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800">${escape_html(themeIcon())}</button> <button class="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800" aria-label="Toggle menu">`);
    {
      $$renderer2.push("<!--[-1-->");
      $$renderer2.push(`<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16"></path></svg>`);
    }
    $$renderer2.push(`<!--]--></button></div></div> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></nav> <main class="mx-auto max-w-7xl px-4 py-6 sm:px-6">`);
    children($$renderer2);
    $$renderer2.push(`<!----></main> <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2"><!--[-->`);
    const each_array = ensure_array_like(toastList);
    for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
      let toast = each_array[$$index];
      $$renderer2.push(`<div${attr_class(`flex items-center gap-3 rounded-lg px-4 py-3 shadow-lg transition-all ${stringify(toast.type === "error" ? "bg-red-600 text-white" : toast.type === "success" ? "bg-emerald-600 text-white" : "bg-zinc-700 text-white")}`)}><span class="text-sm">${escape_html(toast.message)}</span> <button class="ml-2 text-white/70 hover:text-white" aria-label="Dismiss"><svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"></path></svg></button></div>`);
    }
    $$renderer2.push(`<!--]--></div></div>`);
  });
}
export {
  _layout as default
};
