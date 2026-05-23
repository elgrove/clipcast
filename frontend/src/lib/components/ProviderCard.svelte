<script lang="ts">
    import type { AIProvider } from '$lib/types';
    import ProviderBadge from './ProviderBadge.svelte';
    import TestConnectionButton from './TestConnectionButton.svelte';

    let {
        provider,
        onEdit,
        onDelete,
    }: {
        provider: AIProvider;
        onEdit: (p: AIProvider) => void;
        onDelete: (p: AIProvider) => void;
    } = $props();

    let deleting = $state(false);

    async function handleDelete() {
        if (!confirm(`Delete provider "${provider.name}"?`)) return;
        deleting = true;
        onDelete(provider);
    }
</script>

<div class="rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-700 dark:bg-zinc-800/50">
    <div class="flex items-start justify-between gap-4">
        <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
                <ProviderBadge kind={provider.kind} />
                <span class="truncate font-medium text-zinc-900 dark:text-white">
                    {provider.name}
                </span>
                {#if !provider.has_api_key && provider.kind !== 'whisper.cpp'}
                    <span class="rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                        No API key
                    </span>
                {/if}
            </div>
            {#if provider.base_url}
                <p class="mt-1 truncate text-xs text-zinc-500 dark:text-zinc-400">{provider.base_url}</p>
            {/if}
        </div>
        <div class="flex shrink-0 items-center gap-1">
            <TestConnectionButton providerId={provider.id} />
            <button
                onclick={() => onEdit(provider)}
                class="rounded-md px-2 py-1.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-200 hover:text-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-700 dark:hover:text-zinc-200"
            >
                Edit
            </button>
            <button
                onclick={handleDelete}
                disabled={deleting}
                class="rounded-md px-2 py-1.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
            >
                Delete
            </button>
        </div>
    </div>
</div>
