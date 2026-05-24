<script lang="ts">
    import type { AIProvider, ProviderKind } from '$lib/types';
    import { addProvider, updateProvider } from '$lib/api';

    const KIND_INFO: Record<ProviderKind, { label: string }> = {
        'gemini': { label: 'Gemini' },
        'openai': { label: 'OpenAI' },
        'openai-compatible': { label: 'OpenAI-compatible' },
        'openrouter': { label: 'OpenRouter' },
        'whisper.cpp': { label: 'Whisper.cpp' },
    };

    const SINGLE_INSTANCE: ProviderKind[] = ['gemini', 'openai', 'openrouter', 'whisper.cpp'];

    let {
        open = $bindable(false),
        editProvider = null as AIProvider | null,
        existingProviders = [] as AIProvider[],
        onSaved,
    }: {
        open: boolean;
        editProvider?: AIProvider | null;
        existingProviders?: AIProvider[];
        onSaved: (p: AIProvider) => void;
    } = $props();

    let kind = $state<ProviderKind>('gemini');
    let name = $state('');
    let apiKey = $state('');
    let baseUrl = $state('');
    let autoCreateRecommended = $state(false);
    let saving = $state(false);
    let error: string | null = $state(null);

    const availableKinds = $derived.by(() => {
        const taken = new Set(existingProviders.map((p) => p.kind));
        return (Object.keys(KIND_INFO) as ProviderKind[]).filter((k) => {
            if (k === 'openai-compatible') return true;
            return !taken.has(k);
        });
    });

    const hasRecommendations = $derived(kind !== 'openai-compatible');
    const showApiKey = $derived(kind !== 'whisper.cpp');
    const showBaseUrl = $derived(kind === 'openai-compatible' || kind === 'whisper.cpp');
    const requiresName = $derived(kind === 'openai-compatible');

    $effect(() => {
        if (open) {
            error = null;
            if (editProvider) {
                kind = editProvider.kind;
                name = editProvider.name;
                apiKey = '';  // never prefill; user must re-enter to change
                baseUrl = editProvider.base_url;
                autoCreateRecommended = false;
            } else {
                kind = availableKinds[0] ?? 'openai-compatible';
                name = '';
                apiKey = '';
                baseUrl = '';
                // Default ON for first-time setup; OFF for subsequent providers.
                autoCreateRecommended = existingProviders.length === 0;
            }
        }
    });

    $effect(() => {
        if (!hasRecommendations) autoCreateRecommended = false;
    });

    async function handleSave() {
        if (saving) return;
        saving = true;
        error = null;
        try {
            let saved: AIProvider;
            if (editProvider) {
                const patch: { name?: string; api_key?: string; base_url?: string } = {};
                if (name.trim() && name.trim() !== editProvider.name) patch.name = name.trim();
                if (apiKey) patch.api_key = apiKey;
                if (baseUrl !== editProvider.base_url) patch.base_url = baseUrl;
                saved = await updateProvider(editProvider.id, patch);
            } else {
                saved = await addProvider({
                    kind,
                    name: requiresName ? name.trim() : undefined,
                    api_key: apiKey,
                    base_url: baseUrl,
                    auto_create_recommended: autoCreateRecommended,
                });
            }
            onSaved(saved);
            open = false;
        } catch (e: any) {
            error = e.message || 'Failed to save provider';
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
                    {editProvider ? 'Edit provider' : 'Add a provider'}
                </h2>
            </div>

            <div class="space-y-5 px-6 py-5">
                <div>
                    <label for="provider-kind" class="mb-2 block text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Provider</label>
                    <select
                        id="provider-kind"
                        bind:value={kind}
                        disabled={!!editProvider}
                        class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white"
                    >
                        {#each availableKinds as k}
                            <option value={k}>{KIND_INFO[k].label}</option>
                        {/each}
                        {#if editProvider}
                            <option value={editProvider.kind}>{KIND_INFO[editProvider.kind].label}</option>
                        {/if}
                    </select>
                    {#if !editProvider}
                        <p class="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                            We recommend Gemini, or OpenRouter using Google's Gemini models — they give the best ad-detection results.
                        </p>
                    {/if}
                </div>

                {#if requiresName}
                    <div>
                        <label for="provider-name" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            Name <span class="font-normal text-zinc-400">(e.g. Groq, Together)</span>
                        </label>
                        <input
                            id="provider-name"
                            type="text"
                            bind:value={name}
                            disabled={!!editProvider}
                            placeholder="My provider"
                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
                        />
                    </div>
                {/if}

                {#if showApiKey}
                    <div>
                        <label for="provider-api-key" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            API key
                            {#if editProvider && editProvider.has_api_key}
                                <span class="font-normal text-zinc-400">(saved — leave blank to keep)</span>
                            {/if}
                        </label>
                        <input
                            id="provider-api-key"
                            type="password"
                            bind:value={apiKey}
                            placeholder="sk-..."
                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
                        />
                    </div>
                {/if}

                {#if showBaseUrl}
                    <div>
                        <label for="provider-base-url" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            {kind === 'whisper.cpp' ? 'Host URL' : 'Base URL'}
                        </label>
                        <input
                            id="provider-base-url"
                            type="text"
                            bind:value={baseUrl}
                            placeholder={kind === 'whisper.cpp' ? 'http://localhost:8080' : 'https://api.example.com/v1'}
                            class="mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
                        />
                    </div>
                {/if}

                {#if !editProvider && hasRecommendations}
                    <label class="flex items-start gap-2 cursor-pointer">
                        <input
                            type="checkbox"
                            bind:checked={autoCreateRecommended}
                            class="mt-0.5 h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"
                        />
                        <span class="flex-1 text-sm">
                            <span class="block text-zinc-700 dark:text-zinc-300">Create recommended models</span>
                            <span class="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                                Adds the best transcription and analysis models for this provider, and sets them as active.
                            </span>
                        </span>
                    </label>
                {/if}

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
