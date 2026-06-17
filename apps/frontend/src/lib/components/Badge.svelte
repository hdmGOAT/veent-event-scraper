<script lang="ts">
	// Status pill. Maps Organizer/Venue status strings to a color scheme.
	let { status }: { status: string } = $props();

	const styles: Record<string, string> = {
		pending: 'bg-warning-bg text-warning',
		confirmed: 'bg-success-bg text-success',
		verified: 'bg-success-bg text-success',
		rejected: 'bg-danger-bg text-danger'
	};
</script>

<span
	class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize {styles[
		status
	] ?? 'bg-surface-2 text-muted'}"
>
	{status}
</span>
