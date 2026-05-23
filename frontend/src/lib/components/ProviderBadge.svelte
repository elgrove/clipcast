<script lang="ts">
    let { kind }: { kind: string } = $props();

    const styles: Record<string, string> = {
        'gemini': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
        'openai': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'openai-compatible': 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
        'openrouter': 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
        'whisper.cpp': 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
    };

    const labels: Record<string, string> = {
        'gemini': 'Gemini',
        'openai': 'OpenAI',
        'openai-compatible': 'OpenAI-compatible',
        'openrouter': 'OpenRouter',
        'whisper.cpp': 'Whisper.cpp',
    };

    const cls = $derived(styles[kind] ?? 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300');
    const label = $derived(labels[kind] ?? kind);
</script>

<span class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium {cls}">
    {label}
</span>
