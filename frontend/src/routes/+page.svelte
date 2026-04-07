<script lang="ts">
	import { getPodcasts, syncAllPodcasts } from '$lib/api';
	import { toasts } from '$lib/stores';
	import type { PodcastShow } from '$lib/types';

	let podcasts: PodcastShow[] = $state([]);
	let loading = $state(true);
	let syncing = $state(false);

	async function load() {
		try {
			podcasts = await getPodcasts();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to load podcasts');
		} finally {
			loading = false;
		}
	}

	async function handleSyncAll() {
		syncing = true;
		try {
			await syncAllPodcasts();
			toasts.addToast('success', 'Sync queued for all podcasts');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Sync failed');
		} finally {
			syncing = false;
		}
	}

	$effect(() => {
		load();
	});
</script>

<div class="space-y-6">
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<h1 class="text-2xl font-bold text-zinc-900 dark:text-white">Your Podcasts</h1>
		<div class="flex gap-2">
			<button
				onclick={handleSyncAll}
				disabled={syncing}
				class="inline-flex items-center gap-2 rounded-lg bg-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
			>
				<svg class="h-4 w-4 {syncing ? 'animate-spin' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
				</svg>
				{syncing ? 'Syncing...' : 'Refresh All'}
			</button>
			<a
				href="/podcast/add"
				class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
				</svg>
				Add Podcast
			</a>
		</div>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-20">
			<div class="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
		</div>
	{:else if podcasts.length === 0}
		<div class="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-300 py-20 dark:border-zinc-700">
			<svg class="mb-4 h-16 w-16 text-zinc-400 dark:text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
				<path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
			</svg>
			<p class="mb-2 text-lg font-medium text-zinc-500 dark:text-zinc-400">No podcasts yet</p>
			<p class="mb-6 text-sm text-zinc-400 dark:text-zinc-500">Add your first podcast to get started</p>
			<a
				href="/podcast/add"
				class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
			>
				<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
				</svg>
				Add Podcast
			</a>
		</div>
	{:else}
		<div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
			{#each podcasts as podcast (podcast.id)}
				<a
					href="/podcast/{podcast.id}"
					class="group overflow-hidden rounded-xl border border-zinc-200 bg-white transition-all hover:shadow-lg hover:ring-2 hover:ring-emerald-500/30 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"
				>
					<div class="aspect-square overflow-hidden bg-zinc-100 dark:bg-zinc-800">
						{#if podcast.image_url}
							<img
								src={podcast.image_url}
								alt={podcast.title}
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
						<h3 class="line-clamp-2 text-sm font-semibold text-zinc-900 dark:text-white">
							{podcast.title}
						</h3>
						<p class="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
							{podcast.episode_count} episode{podcast.episode_count !== 1 ? 's' : ''}
						</p>
						{#if !podcast.initial_sync_completed}
							<span class="mt-1 inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
								Syncing...
							</span>
						{/if}
					</div>
				</a>
			{/each}
		</div>
	{/if}
</div>
