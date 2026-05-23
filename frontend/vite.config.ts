import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const BACKEND = 'http://localhost:9907';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		host: '0.0.0.0',
		port: 9906,
		strictPort: true,
		proxy: {
			'/api': BACKEND,
			'/feed': BACKEND,
			'/podcasts': BACKEND
		}
	}
});
