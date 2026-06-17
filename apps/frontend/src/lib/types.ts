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
	organizer: string;
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
	rating: number | null;
	verification_status: VenueStatus;
	event_count: number;
	source: string;
}

export interface Scraper {
	key: string;
	last_scraped: string | null;
}

export interface Paginated<T> {
	results: T[];
	total: number;
	pages: number;
	page: number;
}
