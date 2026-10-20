<script lang="ts" module>
	import DOMPurify from 'dompurify';
	import { browser } from '$app/environment';

	// Show notes come from third-party RSS feeds, so the HTML is untrusted and must be
	// sanitised before it reaches {@html}. Open every link in a new tab safely.
	if (browser) {
		DOMPurify.addHook('afterSanitizeAttributes', (node) => {
			if (node.tagName === 'A') {
				node.setAttribute('target', '_blank');
				node.setAttribute('rel', 'noopener noreferrer nofollow');
			}
		});
	}
</script>

<script lang="ts">
	let { html, class: className = '' }: { html: string; class?: string } = $props();

	const clean = $derived(browser ? DOMPurify.sanitize(html) : '');
</script>

<div
	class="prose prose-sm prose-zinc max-w-none [--tw-prose-links:theme(colors.emerald.600)] prose-headings:text-base prose-headings:font-semibold prose-a:font-medium dark:prose-invert dark:[--tw-prose-invert-links:theme(colors.emerald.400)] {className}"
>
	{@html clean}
</div>
