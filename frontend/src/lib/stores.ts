import { writable } from 'svelte/store';

interface Toast {
	id: number;
	type: 'success' | 'error' | 'info';
	message: string;
}

let nextToastId = 0;

function createToastStore() {
	const { subscribe, update } = writable<Toast[]>([]);

	function addToast(type: Toast['type'], message: string, duration = 4000) {
		const id = nextToastId++;
		update((toasts) => [...toasts, { id, type, message }]);
		setTimeout(() => removeToast(id), duration);
	}

	function removeToast(id: number) {
		update((toasts) => toasts.filter((t) => t.id !== id));
	}

	return { subscribe, addToast, removeToast };
}

export const toasts = createToastStore();

type Theme = 'light' | 'dark' | 'auto';

function createThemeStore() {
	const stored = typeof window !== 'undefined' ? localStorage.getItem('theme') : null;
	const initial: Theme = (stored as Theme) || 'dark';
	const { subscribe, set, update } = writable<Theme>(initial);

	function applyTheme(theme: Theme) {
		if (typeof document === 'undefined') return;
		const isDark =
			theme === 'dark' ||
			(theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
		document.documentElement.classList.toggle('dark', isDark);
		document.documentElement.classList.toggle('light', !isDark);
	}

	subscribe((value) => {
		if (typeof window !== 'undefined') {
			localStorage.setItem('theme', value);
			applyTheme(value);
		}
	});

	function cycle() {
		update((current) => {
			const order: Theme[] = ['dark', 'light', 'auto'];
			const idx = order.indexOf(current);
			return order[(idx + 1) % order.length];
		});
	}

	if (typeof window !== 'undefined') {
		applyTheme(initial);
	}

	return { subscribe, set, cycle };
}

export const theme = createThemeStore();
