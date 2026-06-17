<script lang="ts">
	import { page } from '$app/state';
</script>

<svelte:head>
	<title>Error — Veent Admin</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center p-8">
	<div class="w-full max-w-md rounded-xl border border-border bg-surface p-8 text-center">
		<p class="text-5xl font-bold tracking-tight text-accent">{page.status}</p>
		<h1 class="mt-3 text-lg font-semibold text-heading">Something went wrong</h1>
		<p class="mt-2 text-sm text-muted">
			{page.error?.message ?? 'An unexpected error occurred.'}
		</p>
		<a
			href="/"
			class="mt-6 inline-flex items-center justify-center rounded-lg border border-border bg-surface-2 px-4 py-2 text-sm font-medium text-text transition-colors hover:border-accent/50 hover:text-accent"
		>
			Go to Dashboard
		</a>
	</div>
</div>
