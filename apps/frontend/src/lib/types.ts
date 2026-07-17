// Shared types mirroring the Django JSON API payloads (events/views.py api_* views).

export type OrganizerStatus = 'pending' | 'confirmed' | 'rejected';
export type VenueStatus = 'pending' | 'verified' | 'rejected';

export interface Stats {
	total_events: number;
	total_venues: number;
	verified_venues: number;
	total_organizers: number;
	confirmed_organizers: number;
	active_sources: number;
	pending_push: number;
	uncategorized: number;
	dataimpulse_mb: number;
}

export interface SourceCount {
	source: string;
	count: number;
}

export interface CategoryCount {
	category: string;
	count: number;
}

export interface EventRow {
	slug: string;
	name: string;
	starts_at: string | null;
	ends_at: string | null;
	category: string;
	agent_categories: string[];
	source: string;
	price: string;
	venue: string | null;
	venue_slug: string | null;
	organizer: string;
	organizer_slug: string | null;
	url: string;
	image_url: string;
}

export interface Organizer {
	slug: string;
	name: string;
	status: OrganizerStatus;
	email: string;
	phone: string;
	website: string;
	city: string;
	country: string;
	facebook_url: string;
	instagram_url: string;
	description: string;
	source: string;
	scraped_at: string | null;
}

export interface OrganizerDetail extends Organizer {
	address: string;
	source_url: string;
	events: {
		slug: string;
		name: string;
		starts_at: string | null;
		category: string;
		venue: string | null;
	}[];
}

export interface VenueMapPin {
	slug: string;
	name: string;
	address: string;
	city: string;
	country: string;
	primary_type_display: string;
	agents_primary_types: string[];
	rating: number | null;
	latitude: number;
	longitude: number;
	verification_status: VenueStatus;
	website: string;
	event_count: number;
}

export interface VenueRow {
	slug: string;
	name: string;
	city: string;
	country: string;
	primary_type_display: string;
	agents_primary_types: string[];
	rating: number | null;
	verification_status: VenueStatus;
	event_count: number;
	source: string;
}

export interface VenueDetail {
	slug: string;
	name: string;
	address: string;
	city: string;
	country: string;
	website: string;
	rating: number | null;
	about: string;
	primary_type_display: string;
	agents_primary_types: string[];
	verification_status: VenueStatus;
	source: string;
	source_url: string;
	scraped_at: string | null;
	events: {
		slug: string;
		name: string;
		starts_at: string | null;
		category: string;
		organizer: string;
	}[];
}

export type ScraperRunStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled';

export interface ScraperRun {
	id: number;
	scraper_key: string;
	status: ScraperRunStatus;
	started_at: string | null;
	finished_at: string | null;
	created_count: number;
	updated_count: number;
	extra_counts: Record<string, number>;
	error_message: string | null;
	triggered_by: string | null;
	created_at: string;
	duration_seconds: number | null;
	log_output: string | null;
}

export interface ScraperLastRun {
	status: ScraperRunStatus;
	started_at: string | null;
	finished_at: string | null;
	error_message: string | null;
}

export interface Scraper {
	key: string;
	last_scraped: string | null;
	// Most recent ScraperRun for this key (null if it has never been run),
	// annotated by api_scrapers. Drives the card's "last run" line.
	last_run: ScraperLastRun | null;
	// When true, the Scraper Center shows a keyword picker for this scraper and
	// its run accepts query_ids. Returned by api_scrapers.
	supports_keywords: boolean;
	// Derived client-side from the activeRuns poll; not returned by api_scrapers.
	active_run?: ScraperRun | null;
}

export interface Paginated<T> {
	results: T[];
	total: number;
	pages: number;
	page: number;
}

export interface RunAllResult {
	created: { key: string; id: number; status: ScraperRunStatus }[];
	skipped: string[];
}

export interface DedupResult {
	output: string;
	entity: 'events' | 'venues' | 'organizers' | 'all';
}

export interface ScriptStartResult {
	started: boolean;
	script: string;
	pid: number;
}

export interface SearchQuery {
	id: number;
	query: string;
	source: string;
	is_active: boolean;
	last_run_at: string | null;
	events_found_count: number;
	created_at: string;
	updated_at: string;
}
