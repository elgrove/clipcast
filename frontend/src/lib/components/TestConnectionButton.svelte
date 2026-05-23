<script lang="ts">
    import { testProvider } from '$lib/api';
    import type { TestResult } from '$lib/types';

    let { providerId }: { providerId: string } = $props();

    let testing = $state(false);
    let result: TestResult | null = $state(null);

    async function handleTest() {
        testing = true;
        result = null;
        try {
            result = await testProvider(providerId);
        } catch (e: any) {
            result = { ok: false, message: e.message || 'Test failed', latency_ms: 0 };
        } finally {
            testing = false;
        }
    }
</script>

<div class="flex items-center gap-2">
    <button
        onclick={handleTest}
        disabled={testing}
        class="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
    >
        {#if testing}
            <div class="h-3 w-3 animate-spin rounded-full border border-zinc-400 border-t-zinc-700 dark:border-t-zinc-200"></div>
        {:else}
            <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
            </svg>
        {/if}
        Test
    </button>
    {#if result}
        <span class="text-xs {result.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}">
            {#if result.ok}
                ✓ Connected ({result.latency_ms}ms)
            {:else}
                ✗ {result.message}
            {/if}
        </span>
    {/if}
</div>
