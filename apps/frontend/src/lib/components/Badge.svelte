<script lang="ts">
	// Status / category pill.
	// - `status`: maps known Organizer/Venue status strings to a color scheme.
	// - `category`: when provided, derives a deterministic distinct color from the
	//   string so event categories are visually separable (vs. a neutral fallback).
	let { status, category }: { status?: string; category?: string } = $props();

	const styles: Record<string, string> = {
		pending: 'bg-warning-bg text-warning',
		confirmed: 'bg-success-bg text-success',
		verified: 'bg-success-bg text-success',
		rejected: 'bg-danger-bg text-danger'
	};

	// Six distinct accent hues for category badges. Uses semi-transparent
	// backgrounds so they read on the dark surface without new tokens.
	const CATEGORY_COLORS = [
		'bg-accent/15 text-accent',
		'bg-[#a78bfa]/15 text-[#a78bfa]',
		'bg-[#fb923c]/15 text-[#fb923c]',
		'bg-[#f472b6]/15 text-[#f472b6]',
		'bg-warning/15 text-warning',
		'bg-success/15 text-success'
	];

	function categoryClass(value: string): string {
		let hash = 0;
		for (let i = 0; i < value.length; i++) hash += value.charCodeAt(i);
		return CATEGORY_COLORS[hash % CATEGORY_COLORS.length];
	}

	const label = $derived(category ?? status ?? '');
	const colorClass = $derived(
		category ? categoryClass(category) : (styles[status ?? ''] ?? 'bg-surface-2 text-muted')
	);
</script>

<span
	class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize {colorClass}"
>
	{label}
</span>
