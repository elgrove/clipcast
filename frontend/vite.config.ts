import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': 'http://localhost:8906',
			'/feed': 'http://localhost:8906',
			'/podcasts': 'http://localhost:8906'
		}
	}
});
