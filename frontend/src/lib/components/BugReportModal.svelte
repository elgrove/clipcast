<script lang="ts">
	import { submitBugReport } from '$lib/api';
	import { toasts } from '$lib/stores';

	let { open = $bindable(false) }: { open: boolean } = $props();

	let title = $state('');
	let description = $state('');
	let submitting = $state(false);
	let error: string | null = $state(null);

	$effect(() => {
		if (open) {
			title = '';
			description = '';
			error = null;
		}
	});

	async function handleSubmit() {
		if (submitting) return;
		const trimmed = title.trim();
		if (!trimmed) {
			error = 'Please give the bug a title';
			return;
		}
		submitting = true;
		error = null;
		try {
			const result = await submitBugReport({
				title: trimmed,
				description: description.trim(),
				page_url: typeof window !== 'undefined' ? window.location.href : null
			});
			toasts.addToast('success', `Submitted as ${result.identifier} — thank you!`);
			open = false;
		} catch (e: any) {
			error = e?.message || 'Could not submit the report';
		} finally {
			submitting = false;
		}
	}
</script>

{#if open}
	<div class="fixed inset-0 z-40 bg-black/40" onclick={() => (open = false)} role="presentation"></div>

	<div class="fixed inset-0 z-50 flex items-center justify-center p-4">
		<div class="w-full max-w-lg rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
			<div class="border-b border-zinc-200 px-6 py-4 dark:border-zinc-700">
				<h2 class="text-base font-semibold text-zinc-900 dark:text-white">Submit a ticket</h2>
				<p class="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
					This opens an issue in the Clipcast project so it can be looked into.
				</p>
			</div>

			<div class="space-y-5 px-6 py-5">
				<div>
					<label for="bug-title" class="mb-2 block text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
						Title
					</label>
					<input
						id="bug-title"
						type="text"
						bind:value={title}
						placeholder="Short summary of the problem"
						class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
					/>
				</div>

				<div>
					<label for="bug-description" class="mb-2 block text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
						What happened?
					</label>
					<textarea
						id="bug-description"
						bind:value={description}
						rows="5"
						placeholder="Steps to reproduce, what you expected, and what actually happened"
						class="w-full resize-y rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white dark:placeholder-zinc-500"
					></textarea>
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
					onclick={handleSubmit}
					disabled={submitting}
					class="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
				>
					{#if submitting}
						<div class="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
					{/if}
					Submit ticket
				</button>
			</div>
		</div>
	</div>
{/if}
