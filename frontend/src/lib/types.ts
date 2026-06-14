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
	image_url: string | null;
	is_downloaded: boolean;
	is_clipped: boolean;
	is_cleaned: boolean;
	has_transcription: boolean;
	ad_break_count: number;
	ad_break_seconds: number;
	clipping_status: string | null;
}

export interface Advert {
	start_time: string;
	end_time: string;
	advert_for: string;
}

export interface AdBreak {
	start_time: string;
	end_time: string;
	adverts: Advert[] | null;
}

export interface TranscriptionSegment {
	start_time: number;
	end_time: number;
	text: string;
}

export interface EpisodeDetail extends PodcastEpisode {
	podcast_title: string;
	podcast_image_url: string | null;
	audio_url: string | null;
	ad_breaks: AdBreak[];
	report: ClippingReportDetail | null;
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
	boundary_refinement_model_id: string | null;
	keep_raw_episodes: boolean;
	scan_acast_host_reads: boolean;
	transcription_model: AIModel | null;
	analysis_model: AIModel | null;
	boundary_refinement_model: AIModel | null;
}

export type ProviderKind =
	| 'gemini'
	| 'openai'
	| 'openrouter'
	| 'openai-compatible'
	| 'whisper.cpp';

export interface AIProvider {
	id: string;
	kind: ProviderKind;
	name: string;
	base_url: string;
	has_api_key: boolean;
}

export interface AIModel {
	id: string;
	provider_id: string;
	name: string;
	provider_kind: ProviderKind;
	provider_name: string;
	input_price: number;
	output_price: number;
	supports_transcription: boolean;
	supports_analysis: boolean;
	context_window: number;
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
	refined_at: string | null;
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
	refined_at: string | null;
	edited_at: string | null;
	transcription_model: string | null;
	analysis_model: string | null;
	refinement_model: string | null;
	transcription_duration_s: number | null;
	transcription_input_tokens: number | null;
	transcription_output_tokens: number | null;
	transcription_cost: number | null;
	transcription_segments: number | null;
	analysis_duration_s: number | null;
	analysis_input_tokens: number | null;
	analysis_output_tokens: number | null;
	analysis_cost: number | null;
	ad_breaks_found: number | null;
	refinement_duration_s: number | null;
	refinement_input_tokens: number | null;
	refinement_output_tokens: number | null;
	refinement_cost: number | null;
	boundaries_refined: number | null;
	boundaries_snapped: number | null;
	boundaries_kept: number | null;
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
