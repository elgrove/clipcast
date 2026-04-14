<script lang="ts">
	import { goto } from '$app/navigation';
	import { searchItunes, addPodcast } from '$lib/api';
	import { toasts } from '$lib/stores';
	import type { ITunesSearchResult } from '$lib/types';

	let query = $state('');
	let results: ITunesSearchResult[] = $state([]);
	let searching = $state(false);
	let searched = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	let selectedPodcast: ITunesSearchResult | null = $state(null);
	let hasAds = $state(true);
	let adding = $state(false);

	$effect(() => {
		if (debounceTimer) clearTimeout(debounceTimer);
		const q = query.trim();
		if (q.length < 2) {
			results = [];
			searched = false;
			return;
		}
		debounceTimer = setTimeout(async () => {
			searching = true;
			try {
				results = await searchItunes(q);
				searched = true;
			} catch (e: any) {
				toasts.addToast('error', e.message || 'Search failed');
			} finally {
				searching = false;
			}
		}, 300);
	});

	async function handleAdd() {
		if (!selectedPodcast) return;
		adding = true;
		try {
			const podcast = await addPodcast(selectedPodcast.itunes_id, hasAds);
			toasts.addToast('success', `Added "${podcast.title}" to library`);
			goto(`/podcast/${podcast.id}`);
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to add podcast');
		} finally {
			adding = false;
		}
	}
</script>

<div class="space-y-5">
	<div>
		<h1 class="text-2xl font-bold text-zinc-900 dark:text-white">Add Podcast</h1>
		<p class="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Search the iTunes catalogue to find podcasts</p>
	</div>

	<div class="relative">
		<svg class="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
			<path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
		</svg>
		<input
			type="text"
			bind:value={query}
			placeholder="Search for a podcast..."
			class="h-12 w-full rounded-xl border border-zinc-300 bg-white py-3 pl-10 pr-4 text-base outline-none transition-colors focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 sm:h-auto sm:text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-white dark:placeholder-zinc-500 dark:focus:border-emerald-500"
		/>
		{#if searching}
			<div class="absolute right-3 top-1/2 -translate-y-1/2">
				<div class="h-5 w-5 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
			</div>
		{/if}
	</div>

	{#if searched && results.length === 0 && !searching}
		<div class="flex flex-col items-center py-12">
			<p class="text-sm text-zinc-500 dark:text-zinc-400">No results found for "{query}"</p>
		</div>
	{/if}

	{#if results.length > 0}
		<div class="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-4">
			{#each results as result (result.itunes_id)}
				<button
					onclick={() => {
						selectedPodcast = result;
						hasAds = true;
					}}
					class="group overflow-hidden rounded-xl border border-zinc-200 bg-white text-left transition-all hover:shadow-lg hover:ring-2 hover:ring-emerald-500/30 active:scale-[0.98] dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"
				>
					<div class="aspect-square overflow-hidden bg-zinc-100 dark:bg-zinc-800">
						{#if result.artwork_url}
							<img
								src={result.artwork_url}
								alt={result.title}
								class="h-full w-full object-cover transition-transform group-hover:scale-105"
							/>
						{:else}
							<div class="flex h-full w-full items-center justify-center">
								<svg class="h-16 w-16 text-zinc-300 dark:text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
									<path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
								</svg>
							</div>
						{/if}
					</div>
					<div class="p-3">
						<h3 class="line-clamp-2 text-sm font-semibold text-zinc-900 dark:text-white">{result.title}</h3>
						<p class="mt-0.5 line-clamp-1 text-xs text-zinc-500 dark:text-zinc-400">{result.artist}</p>
						{#if result.genre}
							<span class="mt-1 inline-block rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
								{result.genre}
							</span>
						{/if}
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>

{#if selectedPodcast}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-center"
		role="dialog"
		onclick={(e) => { if (e.target === e.currentTarget) selectedPodcast = null; }}
		onkeydown={(e) => { if (e.key === 'Escape') selectedPodcast = null; }}
	>
		<div class="w-full rounded-t-2xl border border-zinc-200 bg-white p-6 shadow-2xl sm:mx-4 sm:max-w-md sm:rounded-2xl dark:border-zinc-700 dark:bg-zinc-900">
			<div class="flex gap-4">
				{#if selectedPodcast.artwork_url}
					<img
						src={selectedPodcast.artwork_url}
						alt={selectedPodcast.title}
						class="h-20 w-20 rounded-lg object-cover"
					/>
				{/if}
				<div class="min-w-0 flex-1">
					<h3 class="text-lg font-semibold text-zinc-900 dark:text-white">{selectedPodcast.title}</h3>
					<p class="text-sm text-zinc-500 dark:text-zinc-400">{selectedPodcast.artist}</p>
				</div>
			</div>

			<label class="mt-6 flex cursor-pointer items-center gap-3 py-1">
				<input
					type="checkbox"
					bind:checked={hasAds}
					class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500 dark:border-zinc-600"
				/>
				<span class="text-sm text-zinc-700 dark:text-zinc-300">This podcast has adverts</span>
			</label>

			<div class="mt-6 flex gap-3 sm:justify-end">
				<button
					onclick={() => (selectedPodcast = null)}
					class="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 sm:flex-initial dark:text-zinc-400 dark:hover:bg-zinc-800"
				>
					Cancel
				</button>
				<button
					onclick={handleAdd}
					disabled={adding}
					class="flex flex-1 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50 sm:flex-initial"
				>
					{#if adding}
						<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
					{/if}
					Add to Library
				</button>
			</div>
		</div>
	</div>
{/if}
