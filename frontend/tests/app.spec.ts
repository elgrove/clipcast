import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
	test('shows app shell with nav links', async ({ page }) => {
		await page.route('**/api/**', (route) => {
			if (route.request().url().includes('/api/podcasts')) {
				return route.fulfill({ status: 200, body: JSON.stringify([]) });
			}
			return route.fulfill({ status: 200, body: '[]' });
		});

		await page.goto('/');
		await expect(page.locator('nav')).toBeVisible();
		await expect(page.getByText('Clipcast')).toBeVisible();
		const nav = page.locator('nav');
		await expect(nav.getByRole('link', { name: 'Podcasts' })).toBeVisible();
		await expect(nav.getByRole('link', { name: 'Add Podcast' })).toBeVisible();
		await expect(nav.getByRole('link', { name: 'Config' })).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/01-navigation.png' });
	});
});

test.describe('Home page', () => {
	test('shows empty state when no podcasts', async ({ page }) => {
		await page.route('**/api/podcasts', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([]),
				});
			}
		});

		await page.goto('/');
		await expect(page.getByText('No podcasts yet')).toBeVisible();
		await expect(page.getByText('Add your first podcast')).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/02-home-empty.png' });
	});

	test('shows podcast grid when podcasts exist', async ({ page }) => {
		await page.route('**/api/podcasts', (route) => {
			if (route.request().method() === 'GET' && !route.request().url().includes('/episodes')) {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify([
						{
							id: '1',
							created_at: '2026-03-28T00:00:00',
							title: 'Test Podcast One',
							description: 'A test podcast',
							itunes_id: '111',
							source_rss_url: 'https://example.com/rss',
							has_ads: true,
							initial_sync_completed: true,
							episode_count: 42,
							image_url: null,
						},
						{
							id: '2',
							created_at: '2026-03-27T00:00:00',
							title: 'Another Show',
							description: 'Another podcast',
							itunes_id: '222',
							source_rss_url: 'https://example.com/rss2',
							has_ads: false,
							initial_sync_completed: true,
							episode_count: 10,
							image_url: null,
						},
					]),
				});
			}
		});

		await page.goto('/');
		await expect(page.getByText('Test Podcast One')).toBeVisible();
		await expect(page.getByText('42 episodes')).toBeVisible();
		await expect(page.getByText('Another Show')).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/03-home-with-podcasts.png' });
	});
});

test.describe('Add Podcast page', () => {
	test('shows search form', async ({ page }) => {
		await page.goto('/podcast/add');
		await expect(page.getByPlaceholder(/search/i)).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/04-add-podcast-search.png' });
	});

	test('displays search results from iTunes', async ({ page }) => {
		await page.route('**/api/search/itunes**', (route) => {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([
					{
						itunes_id: '555',
						title: 'Found Podcast',
						artist: 'Great Host',
						feed_url: 'https://example.com/feed',
						artwork_url: '',
						genre: 'Technology',
						episode_count: 100,
					},
				]),
			});
		});

		await page.goto('/podcast/add');
		await page.getByPlaceholder(/search/i).fill('test podcast');

		// Wait for debounced search to fire
		await page.waitForTimeout(500);

		await expect(page.getByText('Found Podcast')).toBeVisible();
		await expect(page.getByText('Great Host')).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/05-add-podcast-results.png' });
	});
});

test.describe('Config page', () => {
	const mockModels = [
		{
			id: 'm1',
			name: 'gemini-2.5-flash',
			provider: 'gemini',
			host: '',
			api_key: '',
			base_url: '',
			is_preset: true,
			input_price: 0,
			output_price: 0,
			supports_transcription: true,
			supports_analysis: true,
			is_recommended: true,
			display_name: 'Gemini 2.5 Flash',
		},
		{
			id: 'm2',
			name: 'whisper.cpp',
			provider: 'whisper.cpp',
			host: '',
			api_key: '',
			base_url: '',
			is_preset: true,
			input_price: 0,
			output_price: 0,
			supports_transcription: true,
			supports_analysis: false,
			is_recommended: true,
			display_name: 'Whisper.cpp',
		},
		{
			id: 'm3',
			name: 'google/gemini-2.5-flash',
			provider: 'openrouter',
			host: '',
			api_key: '',
			base_url: '',
			is_preset: true,
			input_price: 0,
			output_price: 0,
			supports_transcription: false,
			supports_analysis: true,
			is_recommended: true,
			display_name: 'Gemini 2.5 Flash (via OpenRouter)',
		},
	];

	test('shows config page with model library', async ({ page }) => {
		await page.route('**/api/config', (route) => {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					transcription_model_id: null,
					analysis_model_id: null,
					transcription_model: null,
					analysis_model: null,
				}),
			});
		});

		await page.route('**/api/models', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify(mockModels),
				});
			}
		});

		await page.route('**/api/podcasts', (route) => {
			return route.fulfill({ status: 200, body: JSON.stringify([]) });
		});

		await page.goto('/config');
		await expect(page.getByText('Active Models')).toBeVisible();
		await expect(page.getByText('Model Library')).toBeVisible();
		await expect(page.getByText('Gemini 2.5 Flash')).toBeVisible();
		await expect(page.getByText('Whisper.cpp')).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/06-config-page.png' });
	});

	test('shows add model modal', async ({ page }) => {
		await page.route('**/api/config', (route) => {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					transcription_model_id: null,
					analysis_model_id: null,
					transcription_model: null,
					analysis_model: null,
				}),
			});
		});
		await page.route('**/api/models', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({ status: 200, body: JSON.stringify(mockModels) });
			}
		});
		await page.route('**/api/podcasts', (route) => {
			return route.fulfill({ status: 200, body: JSON.stringify([]) });
		});

		await page.goto('/config');
		await page.getByRole('button', { name: 'Add' }).click();
		await expect(page.getByText('Add a model')).toBeVisible();
		await expect(page.getByText('Gemini')).toBeVisible();
		await expect(page.getByText('OpenAI-compatible')).toBeVisible();
		await expect(page.getByText('OpenRouter')).toBeVisible();
		await expect(page.getByText('Whisper.cpp')).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/06b-config-add-modal.png' });
	});
});

test.describe('Podcast detail page', () => {
	test('shows episode list with actions', async ({ page }) => {
		await page.route('**/api/podcasts/p1', (route) => {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					id: 'p1',
					created_at: '2026-03-28T00:00:00',
					title: 'My Favourite Podcast',
					description: 'A great show about technology and culture.',
					itunes_id: '12345',
					source_rss_url: 'https://example.com/rss',
					has_ads: true,
					initial_sync_completed: true,
					episode_count: 3,
					image_url: null,
				}),
			});
		});

		await page.route('**/api/podcasts/p1/episodes**', (route) => {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					episodes: [
						{
							id: 'e1',
							created_at: '2026-03-28T00:00:00',
							podcast_id: 'p1',
							guid: 'ep-001',
							title: 'Episode 1: The Beginning',
							published_at: '2026-03-25T10:00:00',
							description: 'First episode',
							duration: 3600,
							source_audio_url: 'https://example.com/ep1.mp3',
							is_downloaded: true,
							has_transcription: true,
							ad_count: 3,
							clipping_status: 'completed',
						},
						{
							id: 'e2',
							created_at: '2026-03-27T00:00:00',
							podcast_id: 'p1',
							guid: 'ep-002',
							title: 'Episode 2: Getting Deeper',
							published_at: '2026-03-18T10:00:00',
							description: 'Second episode',
							duration: 2700,
							source_audio_url: 'https://example.com/ep2.mp3',
							is_downloaded: true,
							has_transcription: false,
							ad_count: 0,
							clipping_status: null,
						},
						{
							id: 'e3',
							created_at: '2026-03-26T00:00:00',
							podcast_id: 'p1',
							guid: 'ep-003',
							title: 'Episode 3: The Latest',
							published_at: '2026-03-11T10:00:00',
							description: 'Third episode',
							duration: 1800,
							source_audio_url: 'https://example.com/ep3.mp3',
							is_downloaded: false,
							has_transcription: false,
							ad_count: 0,
							clipping_status: null,
						},
					],
					total: 3,
					page: 1,
					per_page: 50,
					pages: 1,
				}),
			});
		});

		await page.goto('/podcast/p1');
		await expect(page.getByText('My Favourite Podcast')).toBeVisible();
		await expect(page.getByText('Episode 1: The Beginning')).toBeVisible();
		await expect(page.getByText('Episode 2: Getting Deeper')).toBeVisible();
		await expect(page.getByText('Episode 3: The Latest')).toBeVisible();
		await page.screenshot({ path: 'tests/screenshots/07-podcast-detail.png' });
	});
});
