<script lang="ts">
	import {
		getConfig,
		updateConfig,
		getModels,
		deleteModel,
		getProviders,
		deleteProvider,
		getPodcasts,
		exportOpml,
	} from '$lib/api';
	import { toasts, theme } from '$lib/stores';
	import type { Config, AIModel, AIProvider, PodcastShow } from '$lib/types';
	import ModelCard from '$lib/components/ModelCard.svelte';
	import ModelFormModal from '$lib/components/ModelFormModal.svelte';
	import ProviderCard from '$lib/components/ProviderCard.svelte';
	import ProviderFormModal from '$lib/components/ProviderFormModal.svelte';

	let config: Config | null = $state(null);
	let models: AIModel[] = $state([]);
	let providers: AIProvider[] = $state([]);
	let podcasts: PodcastShow[] = $state([]);
	let loading = $state(true);

	let transcriptionModelId = $state('');
	let analysisModelId = $state('');
	let keepRawEpisodes = $state(true);
	let savingConfig = $state(false);
	let savingStorageSetting = $state(false);

	let modelModalOpen = $state(false);
	let editingModel: AIModel | null = $state(null);

	let providerModalOpen = $state(false);
	let editingProvider: AIProvider | null = $state(null);

	let feedType = $state('clipcast');
	let currentTheme = $state('auto');
	theme.subscribe((v) => (currentTheme = v));

	const transcriptionModels = $derived(models.filter((m) => m.supports_transcription));
	const analysisModels = $derived(models.filter((m) => m.supports_analysis));
	const canAddModel = $derived(providers.length > 0);

	async function load() {
		try {
			const [cfg, mdls, provs, pods] = await Promise.all([
				getConfig(),
				getModels(),
				getProviders(),
				getPodcasts(),
			]);
			config = cfg;
			models = mdls;
			providers = provs;
			podcasts = pods;
			transcriptionModelId = cfg.transcription_model_id || '';
			analysisModelId = cfg.analysis_model_id || '';
			keepRawEpisodes = cfg.keep_raw_episodes;
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to load config');
		} finally {
			loading = false;
		}
	}

	async function handleSaveConfig() {
		savingConfig = true;
		try {
			config = await updateConfig({
				transcription_model_id: transcriptionModelId || null,
				analysis_model_id: analysisModelId || null,
			});
			transcriptionModelId = config.transcription_model_id || '';
			analysisModelId = config.analysis_model_id || '';
			toasts.addToast('success', 'Active models saved');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to save');
		} finally {
			savingConfig = false;
		}
	}

	async function handleSaveStorageSetting() {
		savingStorageSetting = true;
		try {
			config = await updateConfig({
				keep_raw_episodes: keepRawEpisodes,
			});
			keepRawEpisodes = config.keep_raw_episodes;
			toasts.addToast('success', 'Storage setting saved');
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to save');
		} finally {
			savingStorageSetting = false;
		}
	}

	function openAddProviderModal() {
		editingProvider = null;
		providerModalOpen = true;
	}

	function openEditProviderModal(p: AIProvider) {
		editingProvider = p;
		providerModalOpen = true;
	}

	async function handleDeleteProvider(p: AIProvider) {
		try {
			await deleteProvider(p.id);
			providers = providers.filter((x) => x.id !== p.id);
			toasts.addToast('success', `Provider "${p.name}" deleted`);
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to delete');
		}
	}

	async function handleProviderSaved(p: AIProvider) {
		const idx = providers.findIndex((x) => x.id === p.id);
		if (idx >= 0) {
			providers = providers.map((x) => (x.id === p.id ? p : x));
		} else {
			providers = [...providers, p];
		}
		// New models and possibly an updated active-models selection may have
		// been created server-side via auto_create_recommended — refresh both.
		const [mdls, cfg] = await Promise.all([getModels(), getConfig()]);
		models = mdls;
		config = cfg;
		transcriptionModelId = cfg.transcription_model_id || '';
		analysisModelId = cfg.analysis_model_id || '';
		toasts.addToast('success', `Provider "${p.name}" saved`);
	}

	function openAddModelModal() {
		if (!canAddModel) return;
		editingModel = null;
		modelModalOpen = true;
	}

	function openEditModelModal(model: AIModel) {
		editingModel = model;
		modelModalOpen = true;
	}

	async function handleDeleteModel(model: AIModel) {
		try {
			await deleteModel(model.id);
			models = models.filter((m) => m.id !== model.id);
			toasts.addToast('success', `"${model.display_name}" deleted`);
		} catch (e: any) {
			toasts.addToast('error', e.message || 'Failed to delete');
		}
	}

	function handleModelSaved(model: AIModel) {
		const idx = models.findIndex((m) => m.id === model.id);
		if (idx >= 0) {
			models = models.map((m) => (m.id === model.id ? model : m));
		} else {
			models = [...models, model];
		}
		toasts.addToast('success', `Model "${model.display_name}" saved`);
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
	<div class="mx-auto max-w-2xl space-y-6">
		<h1 class="text-2xl font-bold text-zinc-900 dark:text-white">Configuration</h1>

		<!-- Provider Library -->
		<div id="provider-library" class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Provider Library</h2>
				<button
					onclick={openAddProviderModal}
					class="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
				>
					<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
					</svg>
					Add
				</button>
			</div>
			<div class="mt-4 space-y-3">
				{#if providers.length === 0}
					<p class="text-sm text-zinc-500 dark:text-zinc-400">No providers yet — add one to get started. Tick "Create recommended models" and we'll set up your active transcription and analysis models in one step.</p>
				{:else}
					{#each providers as p (p.id)}
						<ProviderCard
							provider={p}
							onEdit={openEditProviderModal}
							onDelete={handleDeleteProvider}
						/>
					{/each}
				{/if}
			</div>
		</div>

		<!-- Model Library -->
		<div id="model-library" class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Model Library</h2>
				<button
					onclick={openAddModelModal}
					disabled={!canAddModel}
					title={canAddModel ? '' : 'Add a provider first'}
					class="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-emerald-600"
				>
					<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
					</svg>
					Add
				</button>
			</div>
			<div class="mt-4 space-y-3">
				{#if models.length === 0}
					<p class="text-sm text-zinc-500 dark:text-zinc-400">
						{#if canAddModel}
							No models yet — click Add to configure your first one. You'll need at least a transcription model and an analysis model for clipping to work.
						{:else}
							Add a provider above first.
						{/if}
					</p>
				{:else}
					{#each models as model (model.id)}
						<ModelCard
							{model}
							onEdit={openEditModelModal}
							onDelete={handleDeleteModel}
						/>
					{/each}
				{/if}
			</div>
		</div>

		<!-- Active Models -->
		<div class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Active Models</h2>
			<div class="mt-4 space-y-4">
				<div>
					<label for="transcription-model" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Transcription
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
						Analysis
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
				</div>

				<div class="pt-1">
					<button
						onclick={handleSaveConfig}
						disabled={savingConfig}
						class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
					>
						{#if savingConfig}
							<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
						{/if}
						Save
					</button>
				</div>
			</div>
		</div>

		<!-- Storage -->
		<div class="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
			<h2 class="text-lg font-semibold text-zinc-900 dark:text-white">Storage</h2>
			<div class="mt-4 flex items-start gap-3">
				<input
					id="keep-raw-episodes"
					type="checkbox"
					bind:checked={keepRawEpisodes}
					onchange={handleSaveStorageSetting}
					disabled={savingStorageSetting}
					class="mt-0.5 h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
				/>
				<label for="keep-raw-episodes" class="flex-1 cursor-pointer">
					<span class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
						Keep raw (un-clipped) episode audio
					</span>
					<span class="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
						Preserve the original MP3 alongside the clipped version. Roughly doubles disk
						usage but lets you re-edit episodes if ad detection changes.
					</span>
				</label>
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

<ProviderFormModal
	bind:open={providerModalOpen}
	editProvider={editingProvider}
	existingProviders={providers}
	onSaved={handleProviderSaved}
/>

<ModelFormModal
	bind:open={modelModalOpen}
	editModel={editingModel}
	{providers}
	onSaved={handleModelSaved}
/>
