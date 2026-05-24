<script lang="ts">
    import type { AIModel, AIProvider, ProviderKind } from '$lib/types';
    import { addModel, updateModel } from '$lib/api';

    function getRecommended(k: ProviderKind, tx: boolean, an: boolean): string | null {
        if (k === 'whisper.cpp' || k === 'openai-compatible') return null;
        const onlyTx = tx && !an;
        const onlyAn = an && !tx;
        if (!onlyTx && !onlyAn) return null;
        if (k === 'gemini') return 'gemini-3.1-flash-lite';
        if (k === 'openai') {
            if (onlyTx) return 'gpt-4o-mini-transcribe';
            if (onlyAn) return 'gpt-4.1-mini';
        }
        if (k === 'openrouter') {
            if (onlyTx) return 'openai/whisper-large-v3';
            if (onlyAn) return 'google/gemini-3.1-flash-lite';
        }
        return null;
    }

    let {
        open = $bindable(false),
        editModel = null as AIModel | null,
        providers = [] as AIProvider[],
        onSaved,
    }: {
        open: boolean;
        editModel?: AIModel | null;
        providers: AIProvider[];
        onSaved: (model: AIModel) => void;
    } = $props();

    let providerId = $state('');
    let modelName = $state('');
    let modelSource = $state<'recommended' | 'custom'>('custom');
    let supportsTranscription = $state(true);
    let supportsAnalysis = $state(true);
    let saving = $state(false);
    let error: string | null = $state(null);

    const selectedProvider = $derived(providers.find((p) => p.id === providerId) ?? null);
    const providerKind = $derived<ProviderKind | null>(selectedProvider?.kind ?? null);
    const isWhisper = $derived(providerKind === 'whisper.cpp');

    const recommendedId = $derived(
        providerKind ? getRecommended(providerKind, supportsTranscription, supportsAnalysis) : null
    );

    const customPlaceholder = $derived.by(() => {
        if (providerKind === 'gemini') return 'e.g. gemini-3.1-flash-lite';
        if (providerKind === 'openai' || providerKind === 'openai-compatible') return 'e.g. gpt-4o-mini-transcribe';
        if (providerKind === 'openrouter') return 'e.g. anthropic/claude-3.5-sonnet';
        return 'e.g. model-id';
    });

    $effect(() => {
        if (!open) return;
        error = null;
        if (editModel) {
            providerId = editModel.provider_id;
            modelName = editModel.name;
            supportsTranscription = editModel.supports_transcription;
            supportsAnalysis = editModel.supports_analysis;
            modelSource = 'custom';
        } else {
            providerId = providers[0]?.id ?? '';
            const startKind = providers[0]?.kind ?? null;
            if (startKind === 'whisper.cpp') {
                supportsTranscription = true;
                supportsAnalysis = false;
                modelName = 'whisper.cpp';
                modelSource = 'recommended';
            } else {
                supportsTranscription = true;
                supportsAnalysis = true;
                const rec = startKind ? getRecommended(startKind, true, true) : null;
                modelSource = rec ? 'recommended' : 'custom';
                modelName = rec ?? '';
            }
        }
    });

    // When user is on "recommended", keep modelName synced with the current rec.
    $effect(() => {
        if (!editModel && modelSource === 'recommended' && recommendedId) {
            modelName = recommendedId;
        }
    });

    function handleProviderChange() {
        if (editModel) return;
        if (isWhisper) {
            supportsTranscription = true;
            supportsAnalysis = false;
            modelName = 'whisper.cpp';
            modelSource = 'recommended';
            return;
        }
        supportsTranscription = true;
        supportsAnalysis = true;
        if (providerKind) {
            const rec = getRecommended(providerKind, true, true);
            modelSource = rec ? 'recommended' : 'custom';
            modelName = rec ?? '';
        }
    }

    async function handleSave() {
        if (saving) return;
        saving = true;
        error = null;
        try {
            const name = isWhisper ? 'whisper.cpp' : modelName.trim();
            if (!providerId) throw new Error('Pick a provider');
            if (!name) throw new Error('Model name is required');
            let saved: AIModel;
            if (editModel) {
                saved = await updateModel(editModel.id, {
                    supports_transcription: supportsTranscription,
                    supports_analysis: supportsAnalysis,
                });
            } else {
                saved = await addModel({
                    provider_id: providerId,
                    name,
                    supports_transcription: supportsTranscription,
                    supports_analysis: supportsAnalysis,
                });
            }
            onSaved(saved);
            open = false;
        } catch (e: any) {
            error = e.message || 'Failed to save model';
        } finally {
            saving = false;
        }
    }
</script>

{#if open}
    <div
        class="fixed inset-0 z-40 bg-black/40"
        onclick={() => (open = false)}
        role="presentation"
    ></div>

    <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="w-full max-w-lg rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
            <div class="border-b border-zinc-200 px-6 py-4 dark:border-zinc-700">
                <h2 class="text-base font-semibold text-zinc-900 dark:text-white">
                    {editModel ? 'Edit model' : 'Add a model'}
                </h2>
            </div>

            <div class="space-y-5 px-6 py-5">
                <div>
                    <label for="model-provider" class="mb-2 block text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Provider</label>
                    <select
                        id="model-provider"
                        value={providerId}
                        onchange={(e) => {
                            providerId = e.currentTarget.value;
                            handleProviderChange();
                        }}
                        disabled={!!editModel}
                        class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
                    >
                        {#each providers as p (p.id)}
                            <option value={p.id}>{p.name}</option>
                        {/each}
                    </select>
                </div>

                <!-- Model selector (hidden for whisper.cpp — the name is fixed) -->
                {#if !isWhisper}
                    <div>
                        <p class="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">Model</p>
                        <div class="space-y-2">
                            <label class="flex items-start gap-2 text-sm {recommendedId ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}">
                                <input
                                    type="radio"
                                    name="model-source"
                                    value="recommended"
                                    checked={modelSource === 'recommended'}
                                    onchange={() => (modelSource = 'recommended')}
                                    disabled={!recommendedId || !!editModel}
                                    class="mt-0.5 h-4 w-4 border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                                />
                                <span class="flex-1">
                                    <span class="block text-zinc-700 dark:text-zinc-300">
                                        Recommended{recommendedId ? `: ${recommendedId}` : ''}
                                    </span>
                                    {#if !recommendedId}
                                        <span class="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                                            {#if providerKind === 'openai-compatible'}
                                                No recommendation — enter your endpoint's model id below.
                                            {:else}
                                                Different models are recommended for each task — use Custom, or untick one capability below.
                                            {/if}
                                        </span>
                                    {/if}
                                </span>
                            </label>
                            <label class="flex items-start gap-2 text-sm cursor-pointer">
                                <input
                                    type="radio"
                                    name="model-source"
                                    value="custom"
                                    checked={modelSource === 'custom'}
                                    onchange={() => (modelSource = 'custom')}
                                    disabled={!!editModel}
                                    class="mt-0.5 h-4 w-4 border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                                />
                                <span class="flex-1">
                                    <span class="block text-zinc-700 dark:text-zinc-300">Custom</span>
                                    {#if modelSource === 'custom' || editModel}
                                        <input
                                            id="modal-model-name"
                                            type="text"
                                            bind:value={modelName}
                                            disabled={!!editModel}
                                            placeholder={customPlaceholder}
                                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 disabled:bg-zinc-50 disabled:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500 dark:disabled:bg-zinc-800/50"
                                        />
                                    {/if}
                                </span>
                            </label>
                        </div>
                        {#if supportsAnalysis}
                            <p class="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                                For analysis we recommend a model with at least 256k context.
                                Smaller models still work but episodes longer than 2 hours will be split into overlapping chunks.
                            </p>
                        {/if}
                    </div>
                {/if}

                <div>
                    <p class="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">Use for</p>
                    <div class="flex gap-4">
                        <label class="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300 {isWhisper ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}">
                            <input
                                type="checkbox"
                                bind:checked={supportsTranscription}
                                disabled={isWhisper}
                                class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                            />
                            Transcription
                        </label>
                        <label class="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300 {isWhisper ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}">
                            <input
                                type="checkbox"
                                bind:checked={supportsAnalysis}
                                disabled={isWhisper}
                                class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                            />
                            Analysis
                        </label>
                    </div>
                </div>

                {#if error}
                    <p class="text-sm text-red-600 dark:text-red-400">{error}</p>
                {/if}
            </div>

            <div class="flex justify-end gap-3 border-t border-zinc-200 px-6 py-4 dark:border-zinc-700">
                <button
                    onclick={() => (open = false)}
                    class="rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                >
                    Cancel
                </button>
                <button
                    onclick={handleSave}
                    disabled={saving}
                    class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
                >
                    {#if saving}
                        <div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
                    {/if}
                    Save
                </button>
            </div>
        </div>
    </div>
{/if}
