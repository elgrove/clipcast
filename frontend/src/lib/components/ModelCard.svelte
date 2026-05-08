<script lang="ts">
    import type { AIModel } from '$lib/types';
    import ProviderBadge from './ProviderBadge.svelte';
    import CapabilityBadge from './CapabilityBadge.svelte';
    import TestConnectionButton from './TestConnectionButton.svelte';

    let {
        model,
        onEdit,
        onDelete,
    }: {
        model: AIModel;
        onEdit: (model: AIModel) => void;
        onDelete: (model: AIModel) => void;
    } = $props();

    let deleting = $state(false);

    async function handleDelete() {
        if (!confirm(`Delete "${model.display_name}"?`)) return;
        deleting = true;
        onDelete(model);
    }
</script>

<div class="rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-700 dark:bg-zinc-800/50">
    <div class="flex items-start justify-between gap-4">
        <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
                <ProviderBadge provider={model.provider} />
                <span class="truncate font-medium text-zinc-900 dark:text-white">
                    {model.display_name}
                </span>
                {#if model.is_recommended}
                    <span class="text-xs text-zinc-400">⭐ recommended</span>
                {/if}
            </div>
            <div class="mt-1.5 flex flex-wrap gap-1.5">
                {#if model.supports_transcription}
                    <CapabilityBadge type="transcription" />
                {/if}
                {#if model.supports_analysis}
                    <CapabilityBadge type="analysis" />
                {/if}
            </div>
        </div>
        <div class="flex shrink-0 items-center gap-1">
            <TestConnectionButton provider={model.provider} apiKey={model.api_key} baseUrl={model.base_url} />
            <button
                onclick={() => onEdit(model)}
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
