<script lang="ts">
    import type { AIModel, TestResult } from '$lib/types';
    import { addModel, updateModel, testModelConnection } from '$lib/api';

    type Provider = 'gemini' | 'openai-compatible' | 'openrouter' | 'whisper.cpp';

    const PROVIDER_OPTIONS: { value: Provider; label: string; description: string }[] = [
        { value: 'gemini',            label: 'Gemini',             description: 'Best for transcription + analysis with 1M context.' },
        { value: 'openai-compatible', label: 'OpenAI-compatible',  description: 'Any OpenAI-compatible API endpoint (OpenAI, Azure, etc.).' },
        { value: 'openrouter',        label: 'OpenRouter',         description: 'Route to many models via a single API. Analysis only.' },
        { value: 'whisper.cpp',       label: 'Whisper.cpp',        description: 'Local transcription — free, runs on your hardware. Transcription only.' },
    ];

    const RECOMMENDED_MODELS: Record<Provider, string[]> = {
        'gemini':            ['gemini-2.5-flash', 'gemini-2.5-flash-lite'],
        'openai-compatible': ['gpt-5.4-mini', 'gpt-4.1-mini', 'gpt-4o-transcribe', 'gpt-4o-mini-transcribe'],
        'openrouter':        ['google/gemini-2.5-flash'],
        'whisper.cpp':       [],
    };

    const DEFAULT_MODELS: Record<Provider, string> = {
        'gemini':            'gemini-2.5-flash',
        'openai-compatible': 'gpt-5.4-mini',
        'openrouter':        'google/gemini-2.5-flash',
        'whisper.cpp':       'whisper.cpp',
    };

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
    let apiKey = $state('');
    let baseUrl = $state('');
    let supportsTranscription = $state(true);
    let supportsAnalysis = $state(true);
    let saving = $state(false);
    let testResult: TestResult | null = $state(null);
    let testing = $state(false);
    let showApiKey = $state(false);

    const providerInfo = $derived(PROVIDER_OPTIONS.find((p) => p.value === provider)!);

    $effect(() => {
        if (open) {
            if (editModel) {
                provider = editModel.provider as Provider;
                modelName = editModel.name;
                apiKey = editModel.api_key || '';
                baseUrl = editModel.base_url || '';
                supportsTranscription = editModel.supports_transcription;
                supportsAnalysis = editModel.supports_analysis;
            } else {
                provider = 'gemini';
                modelName = DEFAULT_MODELS['gemini'];
                apiKey = '';
                baseUrl = '';
                supportsTranscription = true;
                supportsAnalysis = true;
            }
            testResult = null;
            showApiKey = false;
        }
    });

    function handleProviderChange(p: Provider) {
        provider = p;
        if (!editModel) {
            modelName = DEFAULT_MODELS[p];
            supportsTranscription = p !== 'openrouter';
            supportsAnalysis = p !== 'whisper.cpp';
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
                    base_url: baseUrl,
                    supports_transcription: supportsTranscription,
                    supports_analysis: supportsAnalysis,
                });
            } else {
                model = await addModel({
                    name: modelName.trim(),
                    provider,
                    api_key: apiKey,
                    base_url: baseUrl,
                    supports_transcription: supportsTranscription,
                    supports_analysis: supportsAnalysis,
                });
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
        testing = true;
        testResult = null;
        try {
            testResult = await testModelConnection({ provider, api_key: apiKey, base_url: baseUrl });
        } catch (e: any) {
            testResult = { ok: false, message: e.message || 'Test failed', latency_ms: 0 };
        } finally {
            testing = false;
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
                <!-- Provider dropdown -->
                <div>
                    <label for="modal-provider" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                        Provider
                    </label>
                    <select
                        id="modal-provider"
                        value={provider}
                        disabled={!!editModel}
                        onchange={(e) => handleProviderChange(e.currentTarget.value as Provider)}
                        class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 disabled:bg-zinc-50 disabled:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:disabled:bg-zinc-800/50"
                    >
                        {#each PROVIDER_OPTIONS as opt}
                            <option value={opt.value}>{opt.label}</option>
                        {/each}
                    </select>
                    <p class="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">{providerInfo.description}</p>
                </div>

                <!-- Recommended model chips -->
                {#if !editModel && RECOMMENDED_MODELS[provider].length > 0}
                    <div>
                        <p class="mb-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">Recommended</p>
                        <div class="flex flex-wrap gap-1.5">
                            {#each RECOMMENDED_MODELS[provider] as rec}
                                <button
                                    onclick={() => (modelName = rec)}
                                    class="rounded border px-2 py-0.5 text-xs transition-colors
                                        {modelName === rec
                                            ? 'border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300'
                                            : 'border-zinc-200 text-zinc-500 hover:border-zinc-300 dark:border-zinc-600 dark:text-zinc-400'}"
                                >
                                    {rec}
                                </button>
                            {/each}
                        </div>
                    </div>
                {/if}

                <!-- Model name (hidden for whisper.cpp) -->
                {#if provider !== 'whisper.cpp'}
                    <div>
                        <label for="modal-model-name" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            Model name
                        </label>
                        <input
                            id="modal-model-name"
                            type="text"
                            bind:value={modelName}
                            disabled={!!editModel}
                            placeholder="e.g. gemini-2.5-flash"
                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 disabled:bg-zinc-50 disabled:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500 dark:disabled:bg-zinc-800/50"
                        />
                    </div>
                {/if}

                <!-- API key with show/hide toggle (hidden for whisper.cpp) -->
                {#if provider !== 'whisper.cpp'}
                    <div>
                        <label for="modal-api-key" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            API key <span class="font-normal text-zinc-400">(saved per model)</span>
                        </label>
                        <div class="relative mt-1">
                            <input
                                id="modal-api-key"
                                type={showApiKey ? 'text' : 'password'}
                                bind:value={apiKey}
                                placeholder="sk-..."
                                class="w-full rounded-lg border border-zinc-300 bg-white py-2 pl-3 pr-10 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
                            />
                            <button
                                type="button"
                                onclick={() => (showApiKey = !showApiKey)}
                                class="absolute inset-y-0 right-0 flex items-center px-3 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                                aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
                            >
                                {#if showApiKey}
                                    <!-- eye-off -->
                                    <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                        <path stroke-linecap="round" stroke-linejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                                    </svg>
                                {:else}
                                    <!-- eye -->
                                    <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                        <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                        <path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                    </svg>
                                {/if}
                            </button>
                        </div>
                    </div>
                {/if}

                <!-- Base URL (openai-compatible and whisper.cpp) -->
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
                        <label class="flex cursor-pointer items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300
                            {provider === 'openrouter' ? 'cursor-not-allowed opacity-50' : ''}">
                            <input
                                type="checkbox"
                                bind:checked={supportsTranscription}
                                disabled={provider === 'openrouter'}
                                class="h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                            />
                            Transcription
                        </label>
                        <label class="flex cursor-pointer items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300
                            {provider === 'whisper.cpp' ? 'cursor-not-allowed opacity-50' : ''}">
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
