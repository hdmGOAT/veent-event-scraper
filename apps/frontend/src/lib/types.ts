// Shared types mirroring the Django JSON API payloads (events/views.py api_* views).

export type OrganizerStatus = 'pending' | 'confirmed' | 'rejected';
export type VenueStatus = 'pending' | 'verified' | 'rejected';

export interface Stats {
	total_events: number;
	total_venues: number;
	verified_venues: number;
	total_organizers: number;
	confirmed_organizers: number;
	pending_organizers: number;
	active_sources: number;
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
}

export interface ScraperLastRun {
	status: ScraperRunStatus;
	started_at: string | null;
	finished_at: string | null;
}

export interface Scraper {
	key: string;
	last_scraped: string | null;
	// Most recent ScraperRun for this key (null if it has never been run),
	// annotated by api_scrapers. Drives the card's "last run" line.
	last_run: ScraperLastRun | null;
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
	entity: string;
}
