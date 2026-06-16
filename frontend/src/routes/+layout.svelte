<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { toasts } from '$lib/stores';
	import { getBugReportsEnabled } from '$lib/api';
	import BugReportModal from '$lib/components/BugReportModal.svelte';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	let mobileMenuOpen = $state(false);
	let adminDropdownOpen = $state(false);
	let bugReportsEnabled = $state(false);
	let bugModalOpen = $state(false);

	onMount(async () => {
		try {
			bugReportsEnabled = await getBugReportsEnabled();
		} catch {
			bugReportsEnabled = false;
		}
	});

	let toastList: { id: number; type: string; message: string }[] = $state([]);
	toasts.subscribe((v) => (toastList = v));

	function closeMobileMenu() {
		mobileMenuOpen = false;
	}

	function closeAdminDropdown() {
		adminDropdownOpen = false;
	}

	const navLinkClass =
		'rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white';
</script>

<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (!target.closest('.admin-dropdown')) {
			adminDropdownOpen = false;
		}
	}}
/>

<div class="min-h-screen bg-zinc-100 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
	<nav class="sticky top-0 z-50 border-b border-zinc-200 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-900/80">
		<div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
			<a href="/" class="text-xl font-bold tracking-tight text-zinc-900 dark:text-white">
				Clipcast
			</a>

			<div class="hidden items-center gap-1 sm:flex">
				<a href="/" class={navLinkClass}>Podcasts</a>
				<a href="/podcast/add" class={navLinkClass}>Add Podcast</a>

				<div class="admin-dropdown relative">
					<button
						onclick={() => (adminDropdownOpen = !adminDropdownOpen)}
						class="{navLinkClass} inline-flex items-center gap-1"
					>
						Admin
						<svg
							class="h-4 w-4 transition-transform {adminDropdownOpen ? 'rotate-180' : ''}"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="2"
						>
							<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
						</svg>
					</button>

					{#if adminDropdownOpen}
						<div class="absolute right-0 mt-1 w-40 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-800">
							<a
								href="/admin/config"
								onclick={closeAdminDropdown}
								class="block px-4 py-2.5 text-sm text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-700"
							>
								Config
							</a>
							<a
								href="/admin/reports"
								onclick={closeAdminDropdown}
								class="block px-4 py-2.5 text-sm text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-700"
							>
								Reports
							</a>
						</div>
					{/if}
				</div>
			</div>

			<div class="sm:hidden">
				<button
					onclick={() => (mobileMenuOpen = !mobileMenuOpen)}
					class="flex h-10 w-10 items-center justify-center rounded-lg text-zinc-500 active:bg-zinc-100 dark:text-zinc-400 dark:active:bg-zinc-800"
					aria-label="Toggle menu"
				>
					{#if mobileMenuOpen}
						<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
						</svg>
					{:else}
						<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
						</svg>
					{/if}
				</button>
			</div>
		</div>

		{#if mobileMenuOpen}
			<div class="border-t border-zinc-200 px-4 pb-3 pt-2 sm:hidden dark:border-zinc-800">
				<a href="/" onclick={closeMobileMenu}
					class="flex h-11 items-center rounded-lg px-3 text-sm font-medium text-zinc-600 active:bg-zinc-100 dark:text-zinc-400 dark:active:bg-zinc-800"
				>
					Podcasts
				</a>
				<a href="/podcast/add" onclick={closeMobileMenu}
					class="flex h-11 items-center rounded-lg px-3 text-sm font-medium text-zinc-600 active:bg-zinc-100 dark:text-zinc-400 dark:active:bg-zinc-800"
				>
					Add Podcast
				</a>
				<div class="my-1 border-t border-zinc-200 dark:border-zinc-700"></div>
				<p class="px-3 py-1 text-xs font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Admin</p>
				<a href="/admin/config" onclick={closeMobileMenu}
					class="flex h-11 items-center rounded-lg px-3 text-sm font-medium text-zinc-600 active:bg-zinc-100 dark:text-zinc-400 dark:active:bg-zinc-800"
				>
					Config
				</a>
				<a href="/admin/reports" onclick={closeMobileMenu}
					class="flex h-11 items-center rounded-lg px-3 text-sm font-medium text-zinc-600 active:bg-zinc-100 dark:text-zinc-400 dark:active:bg-zinc-800"
				>
					Reports
				</a>
			</div>
		{/if}
	</nav>

	<main class="mx-auto max-w-7xl px-4 py-5 sm:px-6 sm:py-6">
		{@render children()}
	</main>

	{#if bugReportsEnabled}
		<footer class="mx-auto max-w-7xl px-4 pb-6 pt-2 sm:px-6">
			<div class="flex justify-center border-t border-zinc-200 pt-4 dark:border-zinc-800">
				<button
					onclick={() => (bugModalOpen = true)}
					class="text-xs text-zinc-400 transition-colors hover:text-zinc-600 dark:text-zinc-600 dark:hover:text-zinc-400"
				>
					Submit a ticket
				</button>
			</div>
		</footer>

		<BugReportModal bind:open={bugModalOpen} />
	{/if}

	<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
		{#each toastList as toast (toast.id)}
			<div
				class="flex items-center gap-3 rounded-lg px-4 py-3 shadow-lg transition-all {toast.type === 'error'
					? 'bg-red-600 text-white'
					: toast.type === 'success'
						? 'bg-emerald-600 text-white'
						: 'bg-zinc-700 text-white'}"
			>
				<span class="text-sm">{toast.message}</span>
				<button
					onclick={() => toasts.removeToast(toast.id)}
					class="ml-2 flex h-6 w-6 flex-shrink-0 items-center justify-center text-white/70 hover:text-white"
					aria-label="Dismiss"
				>
					<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
		{/each}
	</div>
</div>
