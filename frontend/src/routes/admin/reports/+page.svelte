<script lang="ts">
	import { getReports } from '$lib/api';
	import { toasts } from '$lib/stores';
	import type { ClippingReportDetail } from '$lib/types';

	let reports: ClippingReportDetail[] = $state([]);
	let loading = $state(true);

	function formatDuration(seconds: number | null): string {
		if (seconds === null) return '—';
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const m = Math.floor(seconds / 60);
		const s = Math.round(seconds % 60);
		return `${m}m ${s}s`;
	}

	function formatTokens(n: number | null): string {
		if (n === null) return '—';
		if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
		return String(n);
	}

	function formatCost(n: number | null): string {
		if (n === null || n === 0) return '—';
		return `$${n.toFixed(4)}`;
	}

	function formatDate(d: string | null): string {
		if (!d) return '—';
		return new Date(d).toLocaleString('en-GB', {
			day: 'numeric',
			month: 'short',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function statusColour(status: string): string {
		switch (status) {
			case 'completed':
				return 'bg-emerald-500/20 text-emerald-400';
			case 'queued':
				return 'bg-zinc-500/20 text-zinc-400';
			default:
				return 'bg-amber-500/20 text-amber-400';
		}
	}

	function totalCost(report: ClippingReportDetail): number {
		return (report.transcription_cost || 0) + (report.analysis_cost || 0);
	}

	async function load() {
		try {
			reports = await getReports(100);
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to load reports');
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});
</script>

<div class="space-y-5">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-zinc-900 dark:text-white">Clipping Reports</h1>
		<button
			onclick={() => { loading = true; load(); }}
			class="inline-flex h-10 items-center gap-2 rounded-lg bg-zinc-200 px-3 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 active:bg-zinc-400 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
		>
			<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
			</svg>
			<span class="hidden sm:inline">Refresh</span>
		</button>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-20">
			<div class="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
		</div>
	{:else if reports.length === 0}
		<div class="rounded-xl border border-zinc-200 bg-white p-8 text-center dark:border-zinc-800 dark:bg-zinc-900">
			<p class="text-zinc-500 dark:text-zinc-400">No clipping reports yet</p>
		</div>
	{:else}
		<!-- Desktop table (md+) -->
		<div class="hidden overflow-x-auto rounded-xl border border-zinc-200 md:block dark:border-zinc-800">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-zinc-200 bg-zinc-50 text-left text-xs font-medium uppercase tracking-wider text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
						<th class="px-4 py-3">Episode</th>
						<th class="px-4 py-3">Status</th>
						<th class="px-4 py-3">Queued</th>
						<th class="px-4 py-3">Transcription</th>
						<th class="px-4 py-3">Analysis</th>
						<th class="px-4 py-3">Ad breaks</th>
						<th class="px-4 py-3">Tokens</th>
						<th class="px-4 py-3">Cost</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-zinc-200 dark:divide-zinc-800">
					{#each reports as report (report.id)}
						<tr class="bg-white transition-colors hover:bg-zinc-50 dark:bg-zinc-950 dark:hover:bg-zinc-900/50">
							<td class="px-4 py-3">
								<div class="max-w-xs">
									<p class="truncate font-medium text-zinc-900 dark:text-white" title={report.episode_title}>
										{report.episode_title}
									</p>
									<p class="truncate text-xs text-zinc-500 dark:text-zinc-400">
										{report.podcast_title}
									</p>
								</div>
							</td>
							<td class="px-4 py-3">
								<span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium {statusColour(report.status)}">
									{report.status}
									{#if report.has_exceptions}
										<svg class="h-3 w-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
											<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
										</svg>
									{/if}
								</span>
							</td>
							<td class="px-4 py-3 text-zinc-500 dark:text-zinc-400">
								{formatDate(report.queued_at)}
							</td>
							<td class="px-4 py-3">
								{#if report.transcription_duration_s !== null}
									<div class="text-zinc-900 dark:text-zinc-100">
										{formatDuration(report.transcription_duration_s)}
									</div>
									<div class="text-xs text-zinc-500 dark:text-zinc-400">
										{report.transcription_segments ?? '—'} segments
										{#if report.transcription_model}
											<span class="text-zinc-400 dark:text-zinc-500">· {report.transcription_model}</span>
										{/if}
									</div>
								{:else if report.status === 'transcribing'}
									<span class="text-amber-400">in progress...</span>
								{:else}
									<span class="text-zinc-400 dark:text-zinc-600">—</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								{#if report.analysis_duration_s !== null}
									<div class="text-zinc-900 dark:text-zinc-100">
										{formatDuration(report.analysis_duration_s)}
									</div>
									<div class="text-xs text-zinc-500 dark:text-zinc-400">
										{#if report.analysis_model}
											{report.analysis_model}
										{/if}
									</div>
								{:else if report.status === 'analysing'}
									<span class="text-amber-400">in progress...</span>
								{:else}
									<span class="text-zinc-400 dark:text-zinc-600">—</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								{#if report.ad_breaks_found !== null}
									<span class="font-medium text-zinc-900 dark:text-zinc-100">{report.ad_breaks_found}</span>
								{:else}
									<span class="text-zinc-400 dark:text-zinc-600">—</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								{#if report.transcription_input_tokens !== null || report.analysis_input_tokens !== null}
									<div class="text-xs">
										{#if report.transcription_input_tokens !== null}
											<div class="text-zinc-500 dark:text-zinc-400">
												T: {formatTokens(report.transcription_input_tokens)}&darr; {formatTokens(report.transcription_output_tokens)}&uarr;
											</div>
										{/if}
										{#if report.analysis_input_tokens !== null}
											<div class="text-zinc-500 dark:text-zinc-400">
												A: {formatTokens(report.analysis_input_tokens)}&darr; {formatTokens(report.analysis_output_tokens)}&uarr;
											</div>
										{/if}
									</div>
								{:else}
									<span class="text-zinc-400 dark:text-zinc-600">—</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								{#if totalCost(report) > 0}
									<div class="text-xs">
										<div class="text-zinc-900 dark:text-zinc-100">
											{formatCost(totalCost(report))}
										</div>
									</div>
								{:else}
									<span class="text-zinc-400 dark:text-zinc-600">—</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Mobile card list (<md) -->
		<div class="space-y-2 md:hidden">
			{#each reports as report (report.id)}
				<div class="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
					<div class="flex items-start justify-between gap-3">
						<div class="min-w-0 flex-1">
							<p class="text-sm font-medium leading-snug text-zinc-900 dark:text-white">
								{report.episode_title}
							</p>
							<p class="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
								{report.podcast_title}
							</p>
						</div>
						<span class="inline-flex flex-shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium {statusColour(report.status)}">
							{report.status}
							{#if report.has_exceptions}
								<svg class="h-3 w-3 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
								</svg>
							{/if}
						</span>
					</div>
					<div class="mt-3 grid grid-cols-3 gap-3 text-xs">
						<div>
							<span class="text-zinc-500 dark:text-zinc-500">Queued</span>
							<p class="mt-0.5 text-zinc-700 dark:text-zinc-300">{formatDate(report.queued_at)}</p>
						</div>
						<div>
							<span class="text-zinc-500 dark:text-zinc-500">Ad breaks</span>
							<p class="mt-0.5 font-medium text-zinc-700 dark:text-zinc-300">{report.ad_breaks_found ?? '—'}</p>
						</div>
						<div>
							<span class="text-zinc-500 dark:text-zinc-500">Cost</span>
							<p class="mt-0.5 text-zinc-700 dark:text-zinc-300">{totalCost(report) > 0 ? formatCost(totalCost(report)) : '—'}</p>
						</div>
					</div>
					{#if report.transcription_duration_s !== null || report.analysis_duration_s !== null}
						<div class="mt-2 flex gap-3 text-xs text-zinc-500 dark:text-zinc-400">
							{#if report.transcription_duration_s !== null}
								<span>Transcription: {formatDuration(report.transcription_duration_s)}</span>
							{/if}
							{#if report.analysis_duration_s !== null}
								<span>Analysis: {formatDuration(report.analysis_duration_s)}</span>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
