<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getEpisode,
		getEpisodeTranscript,
		getEpisodeStatus,
		clipEpisode,
		cleanupEpisode
	} from '$lib/api';
	import { toasts } from '$lib/stores';
	import { formatDurationShort } from '$lib/utils';
	import ShowNotes from '$lib/components/ShowNotes.svelte';
	import type { EpisodeDetail, TranscriptionSegment, ClippingReport } from '$lib/types';

	let episodeId = $state('');
	page.subscribe((p) => (episodeId = p.params.id ?? ''));

	let episode = $state<EpisodeDetail | null>(null);
	let loading = $state(true);
	let notFound = $state(false);

	let clipping = $state(false);
	let cleaning = $state(false);
	let showDeleteModal = $state(false);

	let reportOpen = $state(false);
	let logsOpen = $state(false);
	let logs = $state<ClippingReport | null>(null);
	let loadingLogs = $state(false);

	let transcriptOpen = $state(false);
	let transcript = $state<TranscriptionSegment[]>([]);
	let transcriptLoaded = $state(false);
	let loadingTranscript = $state(false);

	function formatDate(dateStr: string | null): string {
		if (!dateStr) return '';
		const d = new Date(dateStr);
		const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
		return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
	}

	function formatDateTime(dateStr: string | null): string {
		if (!dateStr) return '';
		const d = new Date(dateStr);
		return d.toLocaleString(undefined, {
			day: 'numeric',
			month: 'short',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatDuration(seconds: number | null): string {
		if (!seconds) return '';
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		return h > 0 ? `${h}h ${m}m` : `${m}m`;
	}

	function hasText(html: string | null): boolean {
		return !!html && html.replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim().length > 0;
	}

	function parseTimeToSeconds(t: string): number {
		if (!t) return 0;
		const parts = t.replace(',', '.').split(':').map(Number);
		if (parts.some(Number.isNaN)) return 0;
		return parts.reduce((acc, p) => acc * 60 + p, 0);
	}

	function statusBadgeClass(status: string): string {
		const classes: Record<string, string> = {
			queued: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
			downloading: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
			transcribing: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400',
			analysing: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
			refining: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400',
			editing: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
			completed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
		};
		return classes[status] || classes.queued;
	}

	const artwork = $derived(episode?.image_url || episode?.podcast_image_url || null);

	const stages = $derived(
		episode?.report
			? [
					{ label: 'Queued', at: episode.report.queued_at },
					{ label: 'Downloaded', at: episode.report.downloaded_at },
					{ label: 'Transcribed', at: episode.report.transcribed_at },
					{ label: 'Analysed', at: episode.report.analysed_at },
					{ label: 'Refined', at: episode.report.refined_at },
					{ label: 'Edited', at: episode.report.edited_at }
				].filter((s) => s.label === 'Queued' || s.at)
			: []
	);

	async function load() {
		loading = true;
		notFound = false;
		try {
			episode = await getEpisode(episodeId);
		} catch (e: any) {
			if (e.status === 404) {
				notFound = true;
			} else {
				toasts.addToast('error', e.message || 'Failed to load episode');
			}
		} finally {
			loading = false;
		}
	}

	async function handleClip() {
		clipping = true;
		try {
			await clipEpisode(episodeId);
			toasts.addToast('success', 'Clipping queued');
			await load();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Clip failed');
		} finally {
			clipping = false;
		}
	}

	async function handleCleanup() {
		cleaning = true;
		showDeleteModal = false;
		try {
			await cleanupEpisode(episodeId);
			toasts.addToast('success', 'Episode cleaned up');
			await load();
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Cleanup failed');
		} finally {
			cleaning = false;
		}
	}

	async function toggleTranscript() {
		transcriptOpen = !transcriptOpen;
		if (transcriptOpen && !transcriptLoaded) {
			loadingTranscript = true;
			try {
				transcript = await getEpisodeTranscript(episodeId);
				transcriptLoaded = true;
			} catch (e: any) {
				toasts.addToast('error', e.message || 'Failed to load transcript');
				transcriptOpen = false;
			} finally {
				loadingTranscript = false;
			}
		}
	}

	async function toggleLogs() {
		logsOpen = !logsOpen;
		if (logsOpen && !logs) {
			loadingLogs = true;
			try {
				logs = await getEpisodeStatus(episodeId);
			} catch {
				// ignore — logs are best-effort
			} finally {
				loadingLogs = false;
			}
		}
	}

	$effect(() => {
		if (!episodeId) return;
		load();
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-20">
		<div class="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
	</div>
{:else if notFound}
	<div class="flex flex-col items-center py-20 text-center">
		<p class="text-sm text-zinc-500 dark:text-zinc-400">Episode not found.</p>
		<a href="/" class="mt-3 text-sm font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400">
			Back to podcasts
		</a>
	</div>
{:else if episode}
	<div class="space-y-6">
		<!-- Back link -->
		<a
			href="/podcast/{episode.podcast_id}"
			class="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-500 transition-colors hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
		>
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
			</svg>
			{episode.podcast_title}
		</a>

		<!-- Header -->
		<div class="flex gap-4 sm:gap-6">
			<div class="h-24 w-24 flex-shrink-0 overflow-hidden rounded-xl bg-zinc-200 sm:h-40 sm:w-40 dark:bg-zinc-800">
				{#if artwork}
					<img src={artwork} alt={episode.title} class="h-full w-full object-cover" />
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<svg class="h-10 w-10 text-zinc-400 sm:h-16 sm:w-16 dark:text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
							<path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
						</svg>
					</div>
				{/if}
			</div>
			<div class="min-w-0 flex-1">
				<h1 class="text-lg font-bold leading-tight text-zinc-900 sm:text-2xl dark:text-white">
					{episode.title}
				</h1>
				<div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-500 dark:text-zinc-400">
					{#if episode.published_at}
						<span>{formatDate(episode.published_at)}</span>
					{/if}
					{#if episode.duration}
						<span>{formatDuration(episode.duration)}</span>
					{/if}
				</div>

				<!-- Status badges -->
				<div class="mt-3 flex flex-wrap gap-1.5">
					{#if episode.is_cleaned}
						<span class="inline-block rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-500">Cleaned</span>
					{:else if episode.is_clipped}
						<span class="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">Clipped</span>
					{:else if episode.is_downloaded}
						<span class="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">Downloaded</span>
					{/if}
					{#if episode.has_transcription && !episode.is_clipped && !episode.is_cleaned}
						<span class="inline-block rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">Transcribed</span>
					{/if}
					{#if episode.clipping_status && episode.clipping_status !== 'completed'}
						<span class="inline-block rounded-full px-2 py-0.5 text-xs font-medium {statusBadgeClass(episode.clipping_status)}">
							{episode.clipping_status}
						</span>
					{/if}
				</div>

				<!-- Actions -->
				<div class="mt-4 flex flex-wrap gap-2">
					<button
						onclick={handleClip}
						disabled={clipping || (episode.clipping_status !== null && episode.clipping_status !== 'completed')}
						class="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
					>
						{#if clipping}
							<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
						{:else}
							<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12" />
							</svg>
						{/if}
						{episode.is_clipped ? 'Re-clip' : 'Clip'}
					</button>
					{#if episode.is_downloaded && !episode.is_cleaned}
						<button
							onclick={() => (showDeleteModal = true)}
							disabled={cleaning}
							class="inline-flex items-center gap-1.5 rounded-lg bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 transition-colors hover:bg-red-200 disabled:opacity-50 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50"
						>
							<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
							</svg>
							Clean up
						</button>
					{/if}
				</div>
			</div>
		</div>

		<!-- Everything below the header only appears once the episode has been clipped -->
		{#if episode.is_clipped}
		<!-- Audio player -->
		{#if episode.audio_url}
			<audio controls src={episode.audio_url} class="w-full">
				Your browser does not support audio playback.
			</audio>
		{:else}
			<div class="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 px-4 py-3 text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900/50 dark:text-zinc-400">
				Ad-free audio hasn't been generated yet — clip this episode to produce it.
			</div>
		{/if}

		<!-- Description -->
		{#if hasText(episode.description)}
			<div>
				<h2 class="text-sm font-semibold text-zinc-900 dark:text-white">Show notes</h2>
				<ShowNotes html={episode.description} class="mt-2" />
			</div>
		{/if}

		<!-- Ad breaks -->
		<div>
			<div class="flex items-baseline justify-between">
				<h2 class="text-sm font-semibold text-zinc-900 dark:text-white">Adverts removed</h2>
				{#if episode.ad_breaks.length > 0}
					<span class="text-xs text-zinc-500 dark:text-zinc-400">
						{episode.ad_break_count} break{episode.ad_break_count !== 1 ? 's' : ''} · {formatDurationShort(episode.ad_break_seconds)} cut
					</span>
				{/if}
			</div>
			{#if episode.ad_breaks.length === 0}
				<p class="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
					No adverts detected.
				</p>
			{:else}
				<ul class="mt-3 space-y-2">
					{#each episode.ad_breaks as adBreak, i (i)}
						{@const dur = parseTimeToSeconds(adBreak.end_time) - parseTimeToSeconds(adBreak.start_time)}
						<li class="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
							<div class="flex items-center justify-between">
								<span class="font-mono text-sm text-zinc-700 dark:text-zinc-300">
									{formatDurationShort(parseTimeToSeconds(adBreak.start_time))} – {formatDurationShort(parseTimeToSeconds(adBreak.end_time))}
								</span>
								<span class="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
									{formatDurationShort(Math.max(0, dur))}
								</span>
							</div>
							{#if adBreak.adverts && adBreak.adverts.length > 0}
								<div class="mt-2 flex flex-wrap gap-1.5">
									{#each adBreak.adverts as ad, j (j)}
										{#if ad.advert_for}
											<span class="rounded-md bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
												{ad.advert_for}
											</span>
										{/if}
									{/each}
								</div>
							{/if}
						</li>
					{/each}
				</ul>
				<p class="mt-2 text-xs text-zinc-400 dark:text-zinc-500">
					Timestamps mark where adverts were in the original audio (removed from the ad-free version).
				</p>
			{/if}
		</div>

		<!-- Clipping report -->
		{#if episode.report}
			<div class="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
				<button
					onclick={() => (reportOpen = !reportOpen)}
					class="flex w-full items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
				>
					<span class="flex items-center gap-2">
						<span class="text-sm font-semibold text-zinc-900 dark:text-white">Processing report</span>
						<span class="inline-block rounded-full px-2 py-0.5 text-xs font-medium {statusBadgeClass(episode.report.status)}">
							{episode.report.status}
						</span>
						{#if episode.report.has_exceptions}
							<span class="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">error</span>
						{/if}
					</span>
					<svg class="h-4 w-4 flex-shrink-0 text-zinc-400 transition-transform {reportOpen ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
					</svg>
				</button>
				{#if reportOpen}
					{@const r = episode.report}
					<div class="space-y-5 border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
						<!-- Timeline -->
						<ol class="space-y-1.5">
							{#each stages as stage (stage.label)}
								<li class="flex items-center justify-between text-sm">
									<span class="flex items-center gap-2 text-zinc-700 dark:text-zinc-300">
										<span class="h-1.5 w-1.5 rounded-full {stage.at ? 'bg-emerald-500' : 'bg-zinc-300 dark:bg-zinc-600'}"></span>
										{stage.label}
									</span>
									<span class="text-zinc-400 dark:text-zinc-500">{stage.at ? formatDateTime(stage.at) : '—'}</span>
								</li>
							{/each}
						</ol>

						<!-- Metrics -->
						<div class="grid gap-3 sm:grid-cols-3">
							{#if r.transcription_model || r.transcription_cost != null}
								<div class="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-800/50">
									<p class="text-xs font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">Transcription</p>
									{#if r.transcription_model}<p class="mt-1 truncate text-sm text-zinc-700 dark:text-zinc-300">{r.transcription_model}</p>{/if}
									{#if r.transcription_segments != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">{r.transcription_segments} segments</p>{/if}
									{#if r.transcription_duration_s != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">{r.transcription_duration_s.toFixed(1)}s</p>{/if}
									{#if r.transcription_cost != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">${r.transcription_cost.toFixed(4)}</p>{/if}
								</div>
							{/if}
							{#if r.analysis_model || r.analysis_cost != null}
								<div class="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-800/50">
									<p class="text-xs font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">Analysis</p>
									{#if r.analysis_model}<p class="mt-1 truncate text-sm text-zinc-700 dark:text-zinc-300">{r.analysis_model}</p>{/if}
									{#if r.ad_breaks_found != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">{r.ad_breaks_found} ad breaks found</p>{/if}
									{#if r.analysis_duration_s != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">{r.analysis_duration_s.toFixed(1)}s</p>{/if}
									{#if r.analysis_cost != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">${r.analysis_cost.toFixed(4)}</p>{/if}
								</div>
							{/if}
							{#if r.refinement_model || r.boundaries_refined != null}
								<div class="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-800/50">
									<p class="text-xs font-medium uppercase tracking-wide text-zinc-400 dark:text-zinc-500">Refinement</p>
									{#if r.refinement_model}<p class="mt-1 truncate text-sm text-zinc-700 dark:text-zinc-300">{r.refinement_model}</p>{/if}
									{#if r.boundaries_refined != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">{r.boundaries_refined} refined · {r.boundaries_snapped ?? 0} snapped · {r.boundaries_kept ?? 0} kept</p>{/if}
									{#if r.refinement_cost != null}<p class="text-xs text-zinc-500 dark:text-zinc-400">${r.refinement_cost.toFixed(4)}</p>{/if}
								</div>
							{/if}
						</div>

						<!-- Logs (lazy) -->
						<div>
							<button
								onclick={toggleLogs}
								class="text-xs font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400"
							>
								{logsOpen ? 'Hide logs' : 'View logs'}
							</button>
							{#if logsOpen}
								{#if loadingLogs}
									<p class="mt-2 text-xs text-zinc-400">Loading…</p>
								{:else if logs}
									{#if logs.exceptions.length > 0}
										<pre class="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-lg bg-red-50 p-3 text-xs text-red-700 dark:bg-red-900/20 dark:text-red-400">{logs.exceptions.join('\n\n')}</pre>
									{/if}
									<pre class="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-lg bg-zinc-900 p-3 text-xs text-zinc-100 dark:bg-black/40">{logs.logs || 'No logs.'}</pre>
								{:else}
									<p class="mt-2 text-xs text-zinc-400">No logs available.</p>
								{/if}
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Transcript -->
		{#if episode.has_transcription}
			<div class="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
				<button
					onclick={toggleTranscript}
					class="flex w-full items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
				>
					<span class="text-sm font-semibold text-zinc-900 dark:text-white">Transcript</span>
					<svg class="h-4 w-4 flex-shrink-0 text-zinc-400 transition-transform {transcriptOpen ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
					</svg>
				</button>
				{#if transcriptOpen}
					<div class="border-t border-zinc-200 dark:border-zinc-800">
						{#if loadingTranscript}
							<div class="flex items-center justify-center py-8">
								<div class="h-6 w-6 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
							</div>
						{:else if transcript.length === 0}
							<p class="px-4 py-6 text-sm text-zinc-500 dark:text-zinc-400">Transcript is empty.</p>
						{:else}
							<div class="max-h-[28rem] divide-y divide-zinc-100 overflow-y-auto dark:divide-zinc-800/70">
								{#each transcript as seg, i (i)}
									<div class="flex gap-3 px-4 py-2">
										<span class="flex-shrink-0 font-mono text-xs text-zinc-400 dark:text-zinc-500">{formatDurationShort(seg.start_time)}</span>
										<span class="text-sm text-zinc-700 dark:text-zinc-300">{seg.text}</span>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		{/if}
		{/if}
	</div>
{/if}

<!-- Clean up confirmation -->
{#if showDeleteModal}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-center"
		role="dialog"
		onclick={(e) => { if (e.target === e.currentTarget) showDeleteModal = false; }}
		onkeydown={(e) => { if (e.key === 'Escape') showDeleteModal = false; }}
	>
		<div class="w-full rounded-t-2xl border border-zinc-200 bg-white p-6 shadow-2xl sm:mx-4 sm:max-w-md sm:rounded-2xl dark:border-zinc-700 dark:bg-zinc-900">
			<h3 class="text-lg font-semibold text-zinc-900 dark:text-white">Clean up episode</h3>
			<p class="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
				This deletes the stored audio and derived files for "{episode?.title}". The episode can be re-clipped later.
			</p>
			<div class="mt-6 flex gap-3 sm:justify-end">
				<button
					onclick={() => (showDeleteModal = false)}
					class="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 sm:flex-initial dark:text-zinc-400 dark:hover:bg-zinc-800"
				>
					Cancel
				</button>
				<button
					onclick={handleCleanup}
					disabled={cleaning}
					class="flex flex-1 items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50 sm:flex-initial"
				>
					{#if cleaning}
						<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
					{/if}
					Clean up
				</button>
			</div>
		</div>
	</div>
{/if}
