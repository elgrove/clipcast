<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getPodcast,
		getEpisodes,
		syncPodcast,
		updatePodcast,
		deletePodcast,
		downloadEpisode,
		clipEpisode,
		batchClipEpisodes,
		getEpisodeStatus
	} from '$lib/api';
	import { toasts } from '$lib/stores';
	import type { PodcastShow, PodcastEpisode, ClippingReport } from '$lib/types';

	let podcastId = $state('');
	page.subscribe((p) => (podcastId = p.params.id ?? ''));

	let podcast: PodcastShow | null = $state(null);
	let episodes: PodcastEpisode[] = $state([]);
	let totalEpisodes = $state(0);
	let currentPage = $state(1);
	let totalPages = $state(1);
	let perPage = $state(50);
	let statusFilter = $state('all');
	let searchQuery = $state('');
	let loading = $state(true);
	let loadingEpisodes = $state(false);

	let syncing = $state(false);
	let showDeleteModal = $state(false);
	let showSettingsModal = $state(false);
	let deleteFiles = $state(false);
	let deleting = $state(false);
	let descriptionExpanded = $state(false);
	let savingSettings = $state(false);
	let settingsHasAds = $state(true);
	let cleanupKeepDays: string = $state('');
	let cleanupKeepCount: string = $state('');

	let selectedIds: Set<string> = $state(new Set());
	let downloadingIds: Set<string> = $state(new Set());
	let clippingIds: Set<string> = $state(new Set());
	let episodeStatuses: Map<string, ClippingReport> = $state(new Map());

	let pollingInterval: ReturnType<typeof setInterval> | undefined;
	let syncPollingInterval: ReturnType<typeof setInterval> | undefined;

	const ACTIVE_STATUSES = ['queued', 'downloading', 'transcribing', 'analysing', 'editing'];

	const filteredEpisodes = $derived(
		searchQuery.trim()
			? episodes.filter((ep) =>
					ep.title.toLowerCase().includes(searchQuery.toLowerCase())
				)
			: episodes
	);

	const allSelected = $derived(
		filteredEpisodes.length > 0 && filteredEpisodes.every((ep) => selectedIds.has(ep.id))
	);

	const selectedCount = $derived(selectedIds.size);

	function formatDuration(seconds: number | null): string {
		if (!seconds) return '';
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		return h > 0 ? `${h}h ${m}m` : `${m}m`;
	}

	function stripHtml(html: string): string {
		return html.replace(/<[^>]*>/g, '');
	}

	function formatDate(dateStr: string | null): string {
		if (!dateStr) return '';
		const d = new Date(dateStr);
		const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
		return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
	}

	function statusBadgeClass(status: string): string {
		const classes: Record<string, string> = {
			queued: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
			downloading: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
			transcribing: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400',
			analysing: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
			editing: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
			completed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
		};
		return classes[status] || classes.queued;
	}

	async function loadPodcast() {
		try {
			podcast = await getPodcast(podcastId);
			initSettingsFields();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to load podcast');
		}
	}

	async function loadEpisodes() {
		loadingEpisodes = true;
		try {
			const data = await getEpisodes(podcastId, currentPage, perPage, statusFilter);
			episodes = data.episodes;
			totalEpisodes = data.total;
			totalPages = data.pages;
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to load episodes');
		} finally {
			loadingEpisodes = false;
		}
	}

	async function handleSync() {
		syncing = true;
		try {
			await syncPodcast(podcastId);
			toasts.addToast('success', 'Sync queued');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Sync failed');
		} finally {
			syncing = false;
		}
	}

	function initSettingsFields() {
		settingsHasAds = podcast?.has_ads ?? true;
		cleanupKeepDays = podcast?.cleanup_keep_days?.toString() ?? '';
		cleanupKeepCount = podcast?.cleanup_keep_count?.toString() ?? '';
	}

	async function handleSaveSettings() {
		if (!podcast) return;
		savingSettings = true;
		try {
			const days = cleanupKeepDays ? parseInt(cleanupKeepDays) : 0;
			const count = cleanupKeepCount ? parseInt(cleanupKeepCount) : 0;
			podcast = await updatePodcast(podcastId, {
				has_ads: settingsHasAds,
				cleanup_keep_days: days,
				cleanup_keep_count: count,
			});
			initSettingsFields();
			showSettingsModal = false;
			toasts.addToast('success', 'Settings saved');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to save settings');
		} finally {
			savingSettings = false;
		}
	}

	async function handleDelete() {
		deleting = true;
		try {
			await deletePodcast(podcastId, deleteFiles);
			toasts.addToast('success', 'Podcast deleted');
			goto('/');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Delete failed');
		} finally {
			deleting = false;
		}
	}

	async function handleDownload(episodeId: string) {
		downloadingIds = new Set([...downloadingIds, episodeId]);
		try {
			await downloadEpisode(episodeId);
			toasts.addToast('success', 'Download complete');
			await loadEpisodes();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Download failed');
		} finally {
			const next = new Set(downloadingIds);
			next.delete(episodeId);
			downloadingIds = next;
		}
	}

	async function handleClip(episodeId: string) {
		clippingIds = new Set([...clippingIds, episodeId]);
		try {
			await clipEpisode(episodeId);
			toasts.addToast('success', 'Clipping queued');
			await loadEpisodes();
			startPolling();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Clip failed');
		} finally {
			const next = new Set(clippingIds);
			next.delete(episodeId);
			clippingIds = next;
		}
	}

	async function handleBatchClip() {
		if (selectedIds.size === 0) return;
		const ids = [...selectedIds];
		for (const id of ids) {
			clippingIds = new Set([...clippingIds, id]);
		}
		try {
			await batchClipEpisodes(ids);
			toasts.addToast('success', `Clipping queued for ${ids.length} episodes`);
			selectedIds = new Set();
			await loadEpisodes();
			startPolling();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Batch clip failed');
		} finally {
			for (const id of ids) {
				const next = new Set(clippingIds);
				next.delete(id);
				clippingIds = next;
			}
		}
	}

	function toggleSelect(id: string) {
		const next = new Set(selectedIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedIds = next;
	}

	function toggleSelectAll() {
		if (allSelected) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(filteredEpisodes.map((ep) => ep.id));
		}
	}

	function changePage(p: number) {
		currentPage = p;
		selectedIds = new Set();
		loadEpisodes();
	}

	function changeStatusFilter(s: string) {
		statusFilter = s;
		currentPage = 1;
		selectedIds = new Set();
		loadEpisodes();
	}

	async function pollStatuses() {
		const activeEpisodes = episodes.filter(
			(ep) => ep.clipping_status && ACTIVE_STATUSES.includes(ep.clipping_status)
		);

		if (activeEpisodes.length === 0) {
			stopPolling();
			return;
		}

		let needsReload = false;
		for (const ep of activeEpisodes) {
			try {
				const status = await getEpisodeStatus(ep.id);
				if (status) {
					const prev = episodeStatuses.get(ep.id);
					if (!prev || prev.status !== status.status) {
						episodeStatuses = new Map(episodeStatuses).set(ep.id, status);
						needsReload = true;
					}
				}
			} catch {
				// ignore polling errors
			}
		}

		if (needsReload) {
			await loadEpisodes();
		}
	}

	function startPolling() {
		if (pollingInterval) return;
		pollingInterval = setInterval(pollStatuses, 3000);
	}

	function stopPolling() {
		if (pollingInterval) {
			clearInterval(pollingInterval);
			pollingInterval = undefined;
		}
	}

	function startSyncPolling() {
		if (syncPollingInterval) return;
		syncPollingInterval = setInterval(async () => {
			await loadPodcast();
			await loadEpisodes();
			if (podcast?.initial_sync_completed && episodes.length > 0) {
				clearInterval(syncPollingInterval);
				syncPollingInterval = undefined;
			}
		}, 3000);
	}

	function stopSyncPolling() {
		if (syncPollingInterval) {
			clearInterval(syncPollingInterval);
			syncPollingInterval = undefined;
		}
	}

	$effect(() => {
		if (!podcastId) return;
		loading = true;
		Promise.all([loadPodcast(), loadEpisodes()]).then(() => {
			loading = false;
			if (!podcast?.initial_sync_completed || episodes.length === 0) {
				startSyncPolling();
			}
			const hasActive = episodes.some(
				(ep) => ep.clipping_status && ACTIVE_STATUSES.includes(ep.clipping_status)
			);
			if (hasActive) startPolling();
		});

		return () => {
			stopPolling();
			stopSyncPolling();
		};
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-20">
		<div class="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
	</div>
{:else if podcast}
	<div class="space-y-6">
		<!-- Podcast Header -->
		<div class="flex flex-col gap-6 sm:flex-row">
			<div class="h-40 w-40 flex-shrink-0 overflow-hidden rounded-xl bg-zinc-200 dark:bg-zinc-800">
				{#if podcast.image_url}
					<img src={podcast.image_url} alt={podcast.title} class="h-full w-full object-cover" />
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<svg class="h-16 w-16 text-zinc-400 dark:text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
							<path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
						</svg>
					</div>
				{/if}
			</div>
			<div class="min-w-0 flex-1">
				<h1 class="text-2xl font-bold text-zinc-900 dark:text-white">{podcast.title}</h1>
				<p class="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
					{podcast.episode_count} episode{podcast.episode_count !== 1 ? 's' : ''}
					{#if podcast.has_ads}
						<span class="ml-2 inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">Has ads</span>
					{/if}
				</p>
				{#if podcast.description}
					{@const cleanDescription = stripHtml(podcast.description)}
					<div class="mt-3">
						<p class="text-sm text-zinc-600 dark:text-zinc-400 {descriptionExpanded ? '' : 'line-clamp-3'}">
							{cleanDescription}
						</p>
						{#if cleanDescription.length > 200}
							<button
								onclick={() => (descriptionExpanded = !descriptionExpanded)}
								class="mt-1 text-xs font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400"
							>
								{descriptionExpanded ? 'Show less' : 'Show more'}
							</button>
						{/if}
					</div>
				{/if}
				<div class="mt-4 flex flex-wrap gap-2">
					<button
						onclick={handleSync}
						disabled={syncing}
						class="inline-flex items-center gap-1.5 rounded-lg bg-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
					>
						<svg class="h-4 w-4 {syncing ? 'animate-spin' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
						</svg>
						Sync
					</button>
					<button
						onclick={() => { initSettingsFields(); showSettingsModal = true; }}
						class="inline-flex items-center gap-1.5 rounded-lg bg-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
					>
						<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
							<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
						</svg>
						Settings
					</button>
					<a
						href="/feed/{podcast.itunes_id}"
						target="_blank"
						class="inline-flex items-center gap-1.5 rounded-lg bg-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
					>
						<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M6 5c7.18 0 13 5.82 13 13M6 11a7 7 0 017 7m-6 0a1 1 0 11-2 0 1 1 0 012 0z" />
						</svg>
						RSS Feed
					</a>
					<button
						onclick={() => (showDeleteModal = true)}
						class="inline-flex items-center gap-1.5 rounded-lg bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 transition-colors hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50"
					>
						<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
						</svg>
						Delete
					</button>
				</div>
			</div>
		</div>

		<!-- Episode Controls -->
		<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
			<div class="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
				<div class="relative flex-1 sm:max-w-xs">
					<svg class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
					</svg>
					<input
						type="text"
						bind:value={searchQuery}
						placeholder="Filter episodes..."
						class="w-full rounded-lg border border-zinc-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-white dark:placeholder-zinc-500"
					/>
				</div>
				<select
					value={statusFilter}
					onchange={(e) => changeStatusFilter(e.currentTarget.value)}
					class="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-white"
				>
					<option value="all">All Episodes</option>
					<option value="downloaded">Downloaded</option>
					<option value="clipped">Clipped</option>
				</select>
			</div>
			{#if selectedCount > 0}
				<button
					onclick={handleBatchClip}
					class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
				>
					<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
						<path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
					Clip Selected ({selectedCount})
				</button>
			{/if}
		</div>

		<!-- Episodes Table -->
		{#if loadingEpisodes}
			<div class="flex items-center justify-center py-12">
				<div class="h-6 w-6 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
			</div>
		{:else if filteredEpisodes.length === 0}
			<div class="flex flex-col items-center py-12">
				{#if !podcast?.initial_sync_completed}
					<div class="h-6 w-6 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
					<p class="mt-4 text-sm text-zinc-500 dark:text-zinc-400">
						Syncing episodes from RSS feed...
					</p>
				{:else}
					<p class="text-sm text-zinc-500 dark:text-zinc-400">
						{searchQuery ? 'No episodes match your search' : 'No episodes found'}
					</p>
				{/if}
			</div>
		{:else}
			<div class="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/50">
								<th class="w-10 px-3 py-3">
									<input
										type="checkbox"
										checked={allSelected}
										onchange={toggleSelectAll}
										class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500 dark:border-zinc-600"
									/>
								</th>
								<th class="px-3 py-3 text-left font-medium text-zinc-600 dark:text-zinc-400">Title</th>
								<th class="hidden px-3 py-3 text-left font-medium text-zinc-600 md:table-cell dark:text-zinc-400">Date</th>
								<th class="hidden px-3 py-3 text-left font-medium text-zinc-600 sm:table-cell dark:text-zinc-400">Duration</th>
								<th class="px-3 py-3 text-left font-medium text-zinc-600 dark:text-zinc-400">Status</th>
								<th class="px-3 py-3 text-right font-medium text-zinc-600 dark:text-zinc-400">Actions</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-zinc-200 dark:divide-zinc-800">
							{#each filteredEpisodes as episode (episode.id)}
								<tr class="bg-white transition-colors hover:bg-zinc-50 dark:bg-zinc-900 dark:hover:bg-zinc-800/50">
									<td class="px-3 py-3">
										<input
											type="checkbox"
											checked={selectedIds.has(episode.id)}
											onchange={() => toggleSelect(episode.id)}
											class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500 dark:border-zinc-600"
										/>
									</td>
									<td class="max-w-xs truncate px-3 py-3 font-medium text-zinc-900 dark:text-white">
										{episode.title}
									</td>
									<td class="hidden whitespace-nowrap px-3 py-3 text-zinc-500 md:table-cell dark:text-zinc-400">
										{formatDate(episode.published_at)}
									</td>
									<td class="hidden whitespace-nowrap px-3 py-3 text-zinc-500 sm:table-cell dark:text-zinc-400">
										{formatDuration(episode.duration)}
									</td>
									<td class="px-3 py-3">
										<div class="flex flex-wrap gap-1">
											{#if episode.is_cleaned}
												<span class="inline-block rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-500">
													Cleaned
												</span>
											{:else if episode.is_clipped}
												<span class="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
													Clipped
												</span>
											{:else if episode.is_downloaded}
												<span class="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
													Downloaded
												</span>
											{/if}
											{#if episode.has_transcription && !episode.is_clipped && !episode.is_cleaned}
												<span class="inline-block rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
													Transcribed
												</span>
											{/if}
											{#if episode.ad_count > 0 && !episode.is_clipped && !episode.is_cleaned}
												<span class="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
													{episode.ad_count} ad{episode.ad_count !== 1 ? 's' : ''}
												</span>
											{/if}
											{#if episode.clipping_status && episode.clipping_status !== 'completed'}
												<span class="inline-block rounded-full px-2 py-0.5 text-xs font-medium {statusBadgeClass(episode.clipping_status)}">
													{episode.clipping_status}
												</span>
											{/if}
										</div>
									</td>
									<td class="px-3 py-3">
										<div class="flex justify-end gap-1">
											{#if !episode.is_downloaded}
												<button
													onclick={() => handleDownload(episode.id)}
													disabled={downloadingIds.has(episode.id)}
													class="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
													title="Download"
												>
													{#if downloadingIds.has(episode.id)}
														<div class="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
													{:else}
														<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
															<path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
														</svg>
													{/if}
												</button>
											{/if}
											<button
												onclick={() => handleClip(episode.id)}
												disabled={clippingIds.has(episode.id) ||
													(episode.clipping_status !== null &&
														episode.clipping_status !== 'completed')}
												class="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
												title="Clip"
											>
												{#if clippingIds.has(episode.id)}
													<div class="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
												{:else}
													<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
														<path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
														<path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
													</svg>
												{/if}
											</button>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Pagination -->
			{#if totalPages > 1}
				<div class="flex items-center justify-between">
					<p class="text-sm text-zinc-500 dark:text-zinc-400">
						Showing {(currentPage - 1) * perPage + 1}–{Math.min(currentPage * perPage, totalEpisodes)} of {totalEpisodes}
					</p>
					<div class="flex gap-1">
						<button
							onclick={() => changePage(currentPage - 1)}
							disabled={currentPage === 1}
							class="rounded-lg px-3 py-1.5 text-sm text-zinc-600 transition-colors hover:bg-zinc-200 disabled:opacity-40 dark:text-zinc-400 dark:hover:bg-zinc-800"
						>
							Previous
						</button>
						{#each Array.from({ length: totalPages }, (_, i) => i + 1) as p}
							{#if p === 1 || p === totalPages || (p >= currentPage - 2 && p <= currentPage + 2)}
								<button
									onclick={() => changePage(p)}
									class="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors {p === currentPage
										? 'bg-emerald-600 text-white'
										: 'text-zinc-600 hover:bg-zinc-200 dark:text-zinc-400 dark:hover:bg-zinc-800'}"
								>
									{p}
								</button>
							{:else if p === currentPage - 3 || p === currentPage + 3}
								<span class="px-1 py-1.5 text-sm text-zinc-400">...</span>
							{/if}
						{/each}
						<button
							onclick={() => changePage(currentPage + 1)}
							disabled={currentPage === totalPages}
							class="rounded-lg px-3 py-1.5 text-sm text-zinc-600 transition-colors hover:bg-zinc-200 disabled:opacity-40 dark:text-zinc-400 dark:hover:bg-zinc-800"
						>
							Next
						</button>
					</div>
				</div>
			{/if}
		{/if}
	</div>
{/if}

<!-- Delete Confirmation Modal -->
{#if showDeleteModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
		role="dialog"
	>
		<div class="mx-4 w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 shadow-2xl dark:border-zinc-700 dark:bg-zinc-900">
			<h3 class="text-lg font-semibold text-zinc-900 dark:text-white">Delete Podcast</h3>
			<p class="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
				Are you sure you want to delete "{podcast?.title}"? This cannot be undone.
			</p>
			<label class="mt-4 flex cursor-pointer items-center gap-3">
				<input
					type="checkbox"
					bind:checked={deleteFiles}
					class="h-4 w-4 rounded border-zinc-300 text-red-600 focus:ring-red-500 dark:border-zinc-600"
				/>
				<span class="text-sm text-zinc-700 dark:text-zinc-300">Also delete downloaded files</span>
			</label>
			<div class="mt-6 flex justify-end gap-3">
				<button
					onclick={() => (showDeleteModal = false)}
					class="rounded-lg px-4 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
				>
					Cancel
				</button>
				<button
					onclick={handleDelete}
					disabled={deleting}
					class="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
				>
					{#if deleting}
						<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
					{/if}
					Delete
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Podcast Settings Modal -->
{#if showSettingsModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
		role="dialog"
	>
		<div class="mx-4 w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 shadow-2xl dark:border-zinc-700 dark:bg-zinc-900">
			<h3 class="text-lg font-semibold text-zinc-900 dark:text-white">Podcast Settings</h3>

			<div class="mt-5 space-y-5">
				<label class="flex cursor-pointer items-center justify-between">
					<div>
						<span class="text-sm font-medium text-zinc-700 dark:text-zinc-300">Clipcast enabled</span>
						<p class="text-xs text-zinc-500 dark:text-zinc-400">Automatically detect and clip adverts from new episodes</p>
					</div>
					<input
						type="checkbox"
						bind:checked={settingsHasAds}
						class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500 dark:border-zinc-600"
					/>
				</label>

				<hr class="border-zinc-200 dark:border-zinc-700" />

				<div>
					<h4 class="text-sm font-medium text-zinc-700 dark:text-zinc-300">Auto cleanup</h4>
					<p class="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
						Delete episode files after clipping. Episodes are kept if they match <strong>either</strong> condition. Leave empty to disable.
					</p>
				</div>
				<div>
					<label for="cleanup-days" class="block text-sm text-zinc-600 dark:text-zinc-400">
						Keep episodes newer than (days)
					</label>
					<input
						id="cleanup-days"
						type="number"
						min="0"
						bind:value={cleanupKeepDays}
						placeholder="e.g. 30"
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-white"
					/>
				</div>
				<div>
					<label for="cleanup-count" class="block text-sm text-zinc-600 dark:text-zinc-400">
						Keep most recent episodes (count)
					</label>
					<input
						id="cleanup-count"
						type="number"
						min="0"
						bind:value={cleanupKeepCount}
						placeholder="e.g. 10"
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900 dark:text-white"
					/>
				</div>
			</div>
			<div class="mt-6 flex justify-end gap-3">
				<button
					onclick={() => (showSettingsModal = false)}
					class="rounded-lg px-4 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
				>
					Cancel
				</button>
				<button
					onclick={handleSaveSettings}
					disabled={savingSettings}
					class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
				>
					{#if savingSettings}
						<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
					{/if}
					Save
				</button>
			</div>
		</div>
	</div>
{/if}
