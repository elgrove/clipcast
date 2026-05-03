<script lang="ts">
    let { type }: { type: 'transcription' | 'analysis' } = $props();
</script>

{#if type === 'transcription'}
    <span class="inline-flex items-center rounded-md bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
        Transcription
    </span>
{:else}
    <span class="inline-flex items-center rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
        Analysis
    </span>
{/if}
