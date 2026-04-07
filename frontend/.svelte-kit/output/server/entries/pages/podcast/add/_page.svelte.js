import { b as attr, c as ensure_array_like, e as escape_html } from "../../../../chunks/index2.js";
import "@sveltejs/kit/internal";
import "../../../../chunks/exports.js";
import "../../../../chunks/utils.js";
import "@sveltejs/kit/internal/server";
import "../../../../chunks/root.js";
import "../../../../chunks/state.svelte.js";
import "../../../../chunks/stores.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let query = "";
    let results = [];
    $$renderer2.push(`<div class="space-y-6"><div><h1 class="text-2xl font-bold text-zinc-900 dark:text-white">Add Podcast</h1> <p class="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Search the iTunes catalogue to find podcasts</p></div> <div class="relative"><svg class="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg> <input type="text"${attr("value", query)} placeholder="Search for a podcast..." class="w-full rounded-xl border border-zinc-300 bg-white py-3 pl-10 pr-4 text-sm outline-none transition-colors focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-white dark:placeholder-zinc-500 dark:focus:border-emerald-500"/> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--> `);
    if (results.length > 0) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4"><!--[-->`);
      const each_array = ensure_array_like(results);
      for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
        let result = each_array[$$index];
        $$renderer2.push(`<button class="group overflow-hidden rounded-xl border border-zinc-200 bg-white text-left transition-all hover:shadow-lg hover:ring-2 hover:ring-emerald-500/30 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"><div class="aspect-square overflow-hidden bg-zinc-100 dark:bg-zinc-800">`);
        if (result.artwork_url) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<img${attr("src", result.artwork_url)}${attr("alt", result.title)} class="h-full w-full object-cover transition-transform group-hover:scale-105"/>`);
        } else {
          $$renderer2.push("<!--[-1-->");
          $$renderer2.push(`<div class="flex h-full w-full items-center justify-center"><svg class="h-16 w-16 text-zinc-300 dark:text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path></svg></div>`);
        }
        $$renderer2.push(`<!--]--></div> <div class="p-3"><h3 class="line-clamp-2 text-sm font-semibold text-zinc-900 dark:text-white">${escape_html(result.title)}</h3> <p class="mt-0.5 line-clamp-1 text-xs text-zinc-500 dark:text-zinc-400">${escape_html(result.artist)}</p> `);
        if (result.genre) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<span class="mt-1 inline-block rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">${escape_html(result.genre)}</span>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--></div></button>`);
      }
      $$renderer2.push(`<!--]--></div>`);
    } else {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]-->`);
  });
}
export {
  _page as default
};
