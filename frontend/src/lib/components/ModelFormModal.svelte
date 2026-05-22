<script lang="ts">
    import type { AIModel } from '$lib/types';
    import { addModel, updateModel } from '$lib/api';
    import { testModel } from '$lib/api';
    import type { TestResult } from '$lib/types';

    type Provider = 'gemini' | 'openai-compatible' | 'openrouter' | 'whisper.cpp';

    const PROVIDER_INFO: Record<Provider, { label: string; description: string }> = {
        'gemini': { label: 'Gemini', description: 'Single model handles transcription and analysis.' },
        'openai-compatible': { label: 'OpenAI-compatible', description: 'Any OpenAI-compatible API endpoint. Different models recommended per task.' },
        'openrouter': { label: 'OpenRouter', description: 'Route to many models via a single API. Different models recommended per task.' },
        'whisper.cpp': { label: 'Whisper.cpp', description: 'Local transcription — free, runs on your hardware. Transcription only.' },
    };

    function getRecommended(p: Provider, tx: boolean, an: boolean): string | null {
        if (p === 'whisper.cpp') return null;
        if (p === 'gemini') return 'gemini-2.5-flash';
        const onlyTx = tx && !an;
        const onlyAn = an && !tx;
        if (p === 'openai-compatible') {
            if (onlyTx) return 'gpt-4o-mini-transcribe';
            if (onlyAn) return 'gpt-4.1-mini';
            return null;
        }
        if (p === 'openrouter') {
            if (onlyTx) return 'openai/whisper-large-v3';
            if (onlyAn) return 'google/gemini-2.5-flash';
            return null;
        }
        return null;
    }

    let {
        open = $bindable(false),
        editModel = null as AIModel | null,
        onSaved,
    }: {
        open: boolean;
        editModel?: AIModel | null;
        onSaved: (model: AIModel) => void;
    } = $props();

    let provider = $state<Provider>('gemini');
    let modelName = $state('gemini-2.5-flash');
    let modelSource = $state<'recommended' | 'custom'>('recommended');
    let apiKey = $state('');
    let baseUrl = $state('');
    let supportsTranscription = $state(true);
    let supportsAnalysis = $state(true);
    let saving = $state(false);
    let testResult: TestResult | null = $state(null);
    let testing = $state(false);
    let savedModelId: string | null = $state(null);

    const recommendedId = $derived(getRecommended(provider, supportsTranscription, supportsAnalysis));

    const customPlaceholder = $derived(
        provider === 'gemini'
            ? 'e.g. gemini-2.5-flash'
            : provider === 'openai-compatible'
                ? 'e.g. gpt-4o-mini-transcribe'
                : provider === 'openrouter'
                    ? 'e.g. anthropic/claude-3.5-sonnet'
                    : 'e.g. model-id'
    );

    $effect(() => {
        if (open) {
            if (editModel) {
                provider = editModel.provider as Provider;
                modelName = editModel.name;
                apiKey = editModel.api_key || '';
                baseUrl = editModel.base_url || '';
                supportsTranscription = editModel.supports_transcription;
                supportsAnalysis = editModel.supports_analysis;
                savedModelId = editModel.id;
                const rec = getRecommended(provider, supportsTranscription, supportsAnalysis);
                modelSource = rec && rec === editModel.name ? 'recommended' : 'custom';
            } else {
                provider = 'gemini';
                supportsTranscription = true;
                supportsAnalysis = true;
                modelSource = 'recommended';
                modelName = getRecommended('gemini', true, true) ?? '';
                apiKey = '';
                baseUrl = '';
                savedModelId = null;
            }
            testResult = null;
        }
    });

    // Keep modelName in sync with recommendedId when user is on "recommended" radio
    $effect(() => {
        if (!editModel && modelSource === 'recommended' && recommendedId) {
            modelName = recommendedId;
        }
    });

    function setProvider(p: Provider) {
        provider = p;
        if (!editModel) {
            if (p === 'whisper.cpp') {
                supportsTranscription = true;
                supportsAnalysis = false;
                modelName = 'whisper.cpp';
                modelSource = 'recommended';
            } else {
                supportsTranscription = true;
                supportsAnalysis = true;
                const rec = getRecommended(p, true, true);
                modelSource = rec ? 'recommended' : 'custom';
                modelName = rec ?? '';
            }
        }
        testResult = null;
    }

    async function handleSave() {
        saving = true;
        try {
            let model: AIModel;
            if (editModel) {
                model = await updateModel(editModel.id, {
                    api_key: apiKey,
                    base_url: baseUrl || (provider === 'whisper.cpp' ? baseUrl : undefined),
                    supports_transcription: supportsTranscription,
                    supports_analysis: supportsAnalysis,
                });
            } else {
                const name = provider === 'whisper.cpp' ? 'whisper.cpp' : modelName.trim();
                model = await addModel({
                    name,
                    provider,
                    api_key: apiKey,
                    base_url: baseUrl,
                    supports_transcription: supportsTranscription,
                    supports_analysis: supportsAnalysis,
                });
                savedModelId = model.id;
            }
            onSaved(model);
            open = false;
        } catch (e: any) {
            alert(e.message || 'Failed to save model');
        } finally {
            saving = false;
        }
    }

    async function handleTest() {
        if (!savedModelId) {
            // Save first then test
            await handleSave();
            return;
        }
        testing = true;
        testResult = null;
        try {
            testResult = await testModel(savedModelId);
        } catch (e: any) {
            testResult = { ok: false, message: e.message || 'Test failed', latency_ms: 0 };
        } finally {
            testing = false;
        }
    }
</script>

{#if open}
    <!-- Backdrop -->
    <div
        class="fixed inset-0 z-40 bg-black/40"
        onclick={() => (open = false)}
        role="presentation"
    ></div>

    <!-- Modal -->
    <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="w-full max-w-lg rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
            <div class="border-b border-zinc-200 px-6 py-4 dark:border-zinc-700">
                <h2 class="text-base font-semibold text-zinc-900 dark:text-white">
                    {editModel ? 'Edit model' : 'Add a model'}
                </h2>
            </div>

            <div class="space-y-5 px-6 py-5">
                <!-- Provider tabs -->
                <div>
                    <p class="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Provider</p>
                    <div class="flex flex-wrap gap-2">
                        {#each Object.entries(PROVIDER_INFO) as [p, info]}
                            <button
                                onclick={() => setProvider(p as Provider)}
                                disabled={!!editModel}
                                class="rounded-md border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-default
                                    {provider === p
                                        ? 'border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                                        : 'border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'}"
                            >
                                {info.label}
                            </button>
                        {/each}
                    </div>
                    <p class="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                        {PROVIDER_INFO[provider].description}
                    </p>
                </div>

                <!-- Model selector (hidden for whisper.cpp) -->
                {#if provider !== 'whisper.cpp'}
                    <div>
                        <p class="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">Model</p>
                        <div class="space-y-2">
                            <label class="flex items-start gap-2 text-sm
                                {recommendedId ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}">
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
                                            Different models are recommended for each task — use Custom, or untick one capability below.
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
                    </div>
                {/if}

                <!-- API key (hidden for whisper.cpp) -->
                {#if provider !== 'whisper.cpp'}
                    <div>
                        <label for="modal-api-key" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            API key <span class="font-normal text-zinc-400">(saved per model)</span>
                        </label>
                        <input
                            id="modal-api-key"
                            type="password"
                            bind:value={apiKey}
                            placeholder="sk-..."
                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
                        />
                    </div>
                {/if}

                <!-- Base URL (shown for openai-compatible and whisper.cpp) -->
                {#if provider === 'openai-compatible' || provider === 'whisper.cpp'}
                    <div>
                        <label for="modal-base-url" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            {provider === 'whisper.cpp' ? 'Host URL' : 'Base URL'}
                        </label>
                        <input
                            id="modal-base-url"
                            type="text"
                            bind:value={baseUrl}
                            placeholder={provider === 'whisper.cpp' ? 'http://localhost:8080' : 'https://api.openai.com/v1'}
                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
                        />
                    </div>
                {/if}

                <!-- Capabilities -->
                <div>
                    <p class="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">Use for</p>
                    <div class="flex gap-4">
                        <label class="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300
                            {provider === 'whisper.cpp' ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}">
                            <input
                                type="checkbox"
                                bind:checked={supportsTranscription}
                                disabled={provider === 'whisper.cpp'}
                                class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                            />
                            Transcription
                        </label>
                        <label class="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300
                            {provider === 'whisper.cpp' ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}">
                            <input
                                type="checkbox"
                                bind:checked={supportsAnalysis}
                                disabled={provider === 'whisper.cpp'}
                                class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                            />
                            Analysis
                        </label>
                    </div>
                </div>

                <!-- Test connection -->
                <div class="flex items-center gap-3">
                    <button
                        onclick={handleTest}
                        disabled={testing || saving}
                        class="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                    >
                        {#if testing}
                            <div class="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-700 dark:border-t-zinc-200"></div>
                        {/if}
                        Test connection
                    </button>
                    {#if testResult}
                        <span class="text-sm {testResult.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}">
                            {testResult.ok ? `✓ Connected (${testResult.latency_ms}ms)` : `✗ ${testResult.message}`}
                        </span>
                    {/if}
                </div>
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
