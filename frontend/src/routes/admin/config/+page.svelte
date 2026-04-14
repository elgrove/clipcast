<script lang="ts">
	import {
		getConfig,
		updateConfig,
		getModels,
		addModel,
		getPodcasts,
		exportOpml
	} from '$lib/api';
	import { toasts, theme } from '$lib/stores';
	import type { Config, AIModel, PodcastShow } from '$lib/types';

	let config: Config | null = $state(null);
	let models: AIModel[] = $state([]);
	let podcasts: PodcastShow[] = $state([]);
	let loading = $state(true);
	let saving = $state(false);

	let geminiApiKey = $state('');
	let transcriptionModelId = $state('');
	let analysisModelId = $state('');

	let newModelName = $state('');
	let newModelProvider = $state('gemini');
	let newModelHost = $state('');
	let addingModel = $state(false);

	let feedType = $state('clipcast');

	let currentTheme = $state('auto');
	theme.subscribe((v) => (currentTheme = v));

	const transcriptionModels = $derived(models);
	const analysisModels = $derived(models.filter((m) => m.provider === 'gemini'));

	async function load() {
		try {
			const [cfg, mdls, pods] = await Promise.all([getConfig(), getModels(), getPodcasts()]);
			config = cfg;
			models = mdls;
			podcasts = pods;
			geminiApiKey = cfg.gemini_api_key || '';
			transcriptionModelId = cfg.transcription_model_id || '';
			analysisModelId = cfg.analysis_model_id || '';
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to load config');
		} finally {
			loading = false;
		}
	}

	async function handleSave() {
		saving = true;
		try {
			config = await updateConfig({
				gemini_api_key: geminiApiKey,
				transcription_model_id: transcriptionModelId || null,
				analysis_model_id: analysisModelId || null
			});
			toasts.addToast('success', 'Config saved');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to save config');
		} finally {
			saving = false;
		}
	}

	async function handleAddModel() {
		if (!newModelName.trim()) return;
		addingModel = true;
		try {
			const model = await addModel({
				name: newModelName.trim(),
				provider: newModelProvider,
				host: newModelHost.trim()
			});
			models = [...models, model];
			toasts.addToast('success', `Model "${model.display_name}" added`);
			newModelName = '';
			newModelHost = '';
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to add model');
		} finally {
			addingModel = false;
		}
	}

	function handleExport() {
		exportOpml(feedType);
		toasts.addToast('info', 'OPML export downloading');
	}

	$effect(() => {
		load();
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-20">
		<div class="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-emerald-500"></div>
	</div>
{:else}
	<div class="mx-auto max-w-2xl space-y-8">
		<h1 class="text-2xl font-bold text-zinc-900 dark:text-white">Configuration</h1>

		<!-- API & Model Settings -->
		<div class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Model Settings</h2>
			<div class="mt-4 space-y-4">
				<div>
					<label for="gemini-key" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Gemini API Key
					</label>
					<input
						id="gemini-key"
						type="password"
						bind:value={geminiApiKey}
						placeholder="Enter your Gemini API key"
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
					/>
				</div>

				<div>
					<label for="transcription-model" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Transcription Model
					</label>
					<select
						id="transcription-model"
						bind:value={transcriptionModelId}
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
					>
						<option value="">None selected</option>
						{#each transcriptionModels as model (model.id)}
							<option value={model.id}>{model.display_name}</option>
						{/each}
					</select>
				</div>

				<div>
					<label for="analysis-model" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Analysis Model
					</label>
					<select
						id="analysis-model"
						bind:value={analysisModelId}
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
					>
						<option value="">None selected</option>
						{#each analysisModels as model (model.id)}
							<option value={model.id}>{model.display_name}</option>
						{/each}
					</select>
					<p class="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Only Gemini models are shown for analysis</p>
				</div>

				<div class="pt-2">
					<button
						onclick={handleSave}
						disabled={saving}
						class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
					>
						{#if saving}
							<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
						{/if}
						Save Settings
					</button>
				</div>
			</div>
		</div>

		<!-- Add Custom Model -->
		<div class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Add Custom Model</h2>
			<div class="mt-4 space-y-4">
				<div>
					<label for="model-name" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Model Name
					</label>
					<input
						id="model-name"
						type="text"
						bind:value={newModelName}
						placeholder="e.g. my-whisper-instance"
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
					/>
				</div>
				<div>
					<label for="model-provider" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Provider
					</label>
					<select
						id="model-provider"
						bind:value={newModelProvider}
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
					>
						<option value="gemini">Gemini</option>
						<option value="whisper.cpp">Whisper.cpp</option>
					</select>
				</div>
				<div>
					<label for="model-host" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Host URL
					</label>
					<input
						id="model-host"
						type="text"
						bind:value={newModelHost}
						placeholder="e.g. http://localhost:8080"
						class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
					/>
				</div>
				<button
					onclick={handleAddModel}
					disabled={addingModel || !newModelName.trim()}
					class="inline-flex items-center gap-2 rounded-lg bg-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
				>
					{#if addingModel}
						<div class="h-4 w-4 animate-spin rounded-full border-2 border-zinc-400 border-t-zinc-700 dark:border-zinc-600 dark:border-t-zinc-300"></div>
					{/if}
					Add Model
				</button>
			</div>
		</div>

		<!-- Appearance -->
		<div class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Appearance</h2>
			<div class="mt-4">
				<label for="theme-select" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
					Theme
				</label>
				<select
					id="theme-select"
					value={currentTheme}
					onchange={(e) => theme.set(e.currentTarget.value as 'light' | 'dark' | 'auto')}
					class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
				>
					<option value="auto">Follow system</option>
					<option value="light">Light</option>
					<option value="dark">Dark</option>
				</select>
				<p class="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Changes are applied immediately</p>
			</div>
		</div>

		<!-- OPML Export -->
		<div class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">OPML Export</h2>
			<p class="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
				Export your podcast subscriptions as an OPML file for use in other podcast apps
			</p>
			<div class="mt-4 space-y-3">
				<div class="flex flex-col gap-2">
					<label class="flex cursor-pointer items-center gap-3">
						<input
							type="radio"
							bind:group={feedType}
							value="clipcast"
							class="h-4 w-4 border-zinc-300 text-emerald-600 focus:ring-emerald-500 dark:border-zinc-600"
						/>
						<div>
							<span class="text-sm font-medium text-zinc-700 dark:text-zinc-300">Clipcast feeds</span>
							<p class="text-xs text-zinc-500 dark:text-zinc-400">Use Clipcast's ad-free RSS feeds</p>
						</div>
					</label>
					<label class="flex cursor-pointer items-center gap-3">
						<input
							type="radio"
							bind:group={feedType}
							value="source"
							class="h-4 w-4 border-zinc-300 text-emerald-600 focus:ring-emerald-500 dark:border-zinc-600"
						/>
						<div>
							<span class="text-sm font-medium text-zinc-700 dark:text-zinc-300">Original feeds</span>
							<p class="text-xs text-zinc-500 dark:text-zinc-400">Use the original source RSS feeds</p>
						</div>
					</label>
				</div>
				<button
					onclick={handleExport}
					disabled={podcasts.length === 0}
					class="inline-flex items-center gap-2 rounded-lg bg-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-300 disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
				>
					<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
					</svg>
					Export OPML
				</button>
				{#if podcasts.length === 0}
					<p class="text-xs text-zinc-500 dark:text-zinc-400">Add some podcasts first before exporting</p>
				{/if}
			</div>
		</div>
	</div>
{/if}
