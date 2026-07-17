<script lang="ts">
	import { page } from '$app/state';

	const errorCode = $derived(page.url.searchParams.get('error'));
	const isLocked = $derived(errorCode === 'locked');
	const hasError = $derived(errorCode === '1' || isLocked);
</script>

<div class="flex min-h-screen items-center justify-center bg-bg px-4">
	<form
		method="POST"
		class="w-full max-w-sm rounded-lg border border-border bg-surface p-6 shadow-lg"
	>
		<h1 class="mb-4 text-lg font-semibold text-heading">Veent Dashboard</h1>

		{#if hasError}
			<p class="mb-3 rounded border border-danger bg-danger-bg px-3 py-2 text-sm text-danger">
				{#if isLocked}
					Account locked — too many failed attempts. Try again later.
				{:else}
					Invalid username or password.
				{/if}
			</p>
		{/if}

		<label class="mb-1 block text-sm text-text" for="username">Username</label>
		<input
			id="username"
			name="username"
			type="text"
			autocomplete="username"
			required
			class="mb-4 w-full rounded border border-border bg-bg px-3 py-2 text-text focus:border-accent focus:outline-none"
		/>

		<label class="mb-1 block text-sm text-text" for="password">Password</label>
		<input
			id="password"
			name="password"
			type="password"
			autocomplete="current-password"
			required
			class="mb-4 w-full rounded border border-border bg-bg px-3 py-2 text-text focus:border-accent focus:outline-none"
		/>

		<button
			type="submit"
			class="w-full rounded bg-accent px-3 py-2 font-medium text-bg hover:bg-accent-dim"
		>
			Sign in
		</button>
	</form>
</div>
