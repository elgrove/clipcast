export interface PodcastShow {
	id: string;
	created_at: string;
	title: string;
	description: string;
	itunes_id: string;
	source_rss_url: string;
	clip_mode: 'off' | 'ai' | 'acast';
	initial_sync_completed: boolean;
	episode_count: number;
	image_url: string | null;
	cleanup_keep_days: number | null;
	cleanup_keep_count: number | null;
	custom_prompt: string;
}

export interface PodcastEpisode {
	id: string;
	created_at: string;
	podcast_id: string;
	guid: string;
	title: string;
	published_at: string | null;
	description: string;
	duration: number | null;
	source_audio_url: string;
	is_downloaded: boolean;
	is_clipped: boolean;
	is_cleaned: boolean;
	has_transcription: boolean;
	ad_count: number;
	clipping_status: string | null;
}

export interface EpisodeListResponse {
	episodes: PodcastEpisode[];
	total: number;
	page: number;
	per_page: number;
	pages: number;
}

export interface Config {
	transcription_model_id: string | null;
	analysis_model_id: string | null;
	gemini_api_key?: string;
	transcription_model: AIModel | null;
	analysis_model: AIModel | null;
}

export interface AIModel {
	id: string;
	name: string;
	provider: string;
	host: string;
	api_key: string;
	base_url: string;
	is_preset: boolean;
	input_price: number;
	output_price: number;
	supports_transcription: boolean;
	supports_analysis: boolean;
	is_recommended: boolean;
	display_name: string;
}

export interface TestResult {
	ok: boolean;
	message: string;
	latency_ms: number;
}

export interface ClippingReport {
	id: string;
	episode_id: string;
	status: string;
	queued_at: string;
	downloaded_at: string | null;
	transcribed_at: string | null;
	analysed_at: string | null;
	edited_at: string | null;
	logs: string;
	exceptions: string[];
}

export interface ClippingReportDetail {
	id: string;
	episode_id: string;
	episode_title: string;
	podcast_title: string;
	status: string;
	queued_at: string;
	downloaded_at: string | null;
	transcribed_at: string | null;
	analysed_at: string | null;
	edited_at: string | null;
	transcription_model: string | null;
	analysis_model: string | null;
	transcription_duration_s: number | null;
	transcription_input_tokens: number | null;
	transcription_output_tokens: number | null;
	transcription_cost: number | null;
	transcription_segments: number | null;
	analysis_duration_s: number | null;
	analysis_input_tokens: number | null;
	analysis_output_tokens: number | null;
	analysis_cost: number | null;
	adverts_found: number | null;
	has_exceptions: boolean;
}

export interface ITunesSearchResult {
	itunes_id: string;
	title: string;
	artist: string;
	feed_url: string;
	artwork_url: string;
	genre: string;
	episode_count: number | null;
	ads_by_acast: boolean;
}
