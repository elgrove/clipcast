import type {
	PodcastShow,
	PodcastEpisode,
	EpisodeListResponse,
	Config,
	AIModel,
	AIProvider,
	ProviderKind,
	TestResult,
	ClippingReport,
	ClippingReportDetail,
	ITunesSearchResult
} from './types';

const BASE_URL = '';

class ApiError extends Error {
	status: number;
	constructor(message: string, status: number) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
	const response = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json', ...options?.headers },
		...options
	});

	if (!response.ok) {
		let message = `Request failed (${response.status})`;
		try {
			const body = await response.json();
			if (body.detail) message = body.detail;
		} catch {
			// use default message
		}
		throw new ApiError(message, response.status);
	}

	if (response.status === 204) return undefined as T;

	return response.json();
}

export async function getPodcasts(): Promise<PodcastShow[]> {
	return fetchApi<PodcastShow[]>('/api/podcasts');
}

export async function getPodcast(id: string): Promise<PodcastShow> {
	return fetchApi<PodcastShow>(`/api/podcasts/${id}`);
}

export async function addPodcast(itunesId: string, clipMode: string): Promise<PodcastShow> {
	return fetchApi<PodcastShow>('/api/podcasts', {
		method: 'POST',
		body: JSON.stringify({ itunes_id: itunesId, clip_mode: clipMode })
	});
}

export async function deletePodcast(id: string, deleteFiles = false): Promise<void> {
	return fetchApi<void>(`/api/podcasts/${id}?delete_files=${deleteFiles}`, {
		method: 'DELETE'
	});
}

export async function updatePodcast(
	id: string,
	data: {
		clip_mode?: string;
		cleanup_keep_days?: number | null;
		cleanup_keep_count?: number | null;
		custom_prompt?: string;
	}
): Promise<PodcastShow> {
	return fetchApi<PodcastShow>(`/api/podcasts/${id}`, {
		method: 'PATCH',
		body: JSON.stringify(data)
	});
}

export async function syncPodcast(id: string): Promise<void> {
	await fetchApi(`/api/podcasts/${id}/sync`, { method: 'POST' });
}

export async function syncAllPodcasts(): Promise<void> {
	await fetchApi('/api/podcasts/sync-all', { method: 'POST' });
}

export async function getEpisodes(
	podcastId: string,
	page = 1,
	perPage = 50,
	status = 'all'
): Promise<EpisodeListResponse> {
	const params = new URLSearchParams({
		page: String(page),
		per_page: String(perPage),
		status
	});
	return fetchApi<EpisodeListResponse>(
		`/api/podcasts/${podcastId}/episodes?${params}`
	);
}

export async function downloadEpisode(id: string): Promise<void> {
	await fetchApi(`/api/episodes/${id}/download`, { method: 'POST' });
}

export async function cleanupEpisode(id: string): Promise<void> {
	await fetchApi(`/api/episodes/${id}`, { method: 'DELETE' });
}

export async function clipEpisode(id: string): Promise<{ report_id: string }> {
	return fetchApi<{ report_id: string }>(`/api/episodes/${id}/clip`, {
		method: 'POST'
	});
}

export async function clipAllEpisodes(podcastId: string): Promise<{ report_ids: string[] }> {
	return fetchApi<{ report_ids: string[] }>(`/api/podcasts/${podcastId}/clip-all`, {
		method: 'POST'
	});
}

export async function batchClipEpisodes(
	episodeIds: string[]
): Promise<{ report_ids: string[] }> {
	return fetchApi<{ report_ids: string[] }>('/api/episodes/batch-clip', {
		method: 'POST',
		body: JSON.stringify({ episode_ids: episodeIds })
	});
}

export async function getEpisodeStatus(id: string): Promise<ClippingReport | null> {
	return fetchApi<ClippingReport | null>(`/api/episodes/${id}/status`);
}

export async function getConfig(): Promise<Config> {
	return fetchApi<Config>('/api/config');
}

export async function updateConfig(
	data: Partial<{
		transcription_model_id: string | null;
		analysis_model_id: string | null;
		keep_raw_episodes: boolean;
	}>
): Promise<Config> {
	return fetchApi<Config>('/api/config', {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export async function getModels(): Promise<AIModel[]> {
	return fetchApi<AIModel[]>('/api/models');
}

export async function addModel(data: {
	provider_id: string;
	name: string;
	supports_transcription?: boolean;
	supports_analysis?: boolean;
}): Promise<AIModel> {
	return fetchApi<AIModel>('/api/models', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export async function updateModel(
	id: string,
	data: {
		name?: string;
		supports_transcription?: boolean;
		supports_analysis?: boolean;
		input_price?: number;
		output_price?: number;
	}
): Promise<AIModel> {
	return fetchApi<AIModel>(`/api/models/${id}`, {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export async function deleteModel(id: string): Promise<void> {
	return fetchApi<void>(`/api/models/${id}`, { method: 'DELETE' });
}

export async function getProviders(): Promise<AIProvider[]> {
	return fetchApi<AIProvider[]>('/api/providers');
}

export async function addProvider(data: {
	kind: ProviderKind;
	name?: string;
	api_key?: string;
	base_url?: string;
	auto_create_recommended?: boolean;
}): Promise<AIProvider> {
	return fetchApi<AIProvider>('/api/providers', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export async function updateProvider(
	id: string,
	data: { name?: string; api_key?: string; base_url?: string }
): Promise<AIProvider> {
	return fetchApi<AIProvider>(`/api/providers/${id}`, {
		method: 'PATCH',
		body: JSON.stringify(data)
	});
}

export async function deleteProvider(id: string): Promise<void> {
	return fetchApi<void>(`/api/providers/${id}`, { method: 'DELETE' });
}

export async function testProvider(id: string): Promise<TestResult> {
	return fetchApi<TestResult>(`/api/providers/${id}/test`, { method: 'POST' });
}

export async function searchItunes(query: string): Promise<ITunesSearchResult[]> {
	return fetchApi<ITunesSearchResult[]>(
		`/api/search/itunes?q=${encodeURIComponent(query)}`
	);
}

export async function getReports(limit = 50): Promise<ClippingReportDetail[]> {
	return fetchApi<ClippingReportDetail[]>(`/api/reports?limit=${limit}`);
}

export function exportOpml(feedType: string): void {
	const params = new URLSearchParams({ feed_type: feedType });
	window.location.href = `${BASE_URL}/api/config/export-opml?${params}`;
}
