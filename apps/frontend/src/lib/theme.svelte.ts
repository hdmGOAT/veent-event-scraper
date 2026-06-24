// Reactive shared theme state for Svelte 5 runes.
// Any component that reads `themeStore.current` inside a $effect or $derived
// will automatically re-run when the theme is toggled.
let _theme = $state<'dark' | 'light'>('dark');

export const themeStore = {
	get current(): 'dark' | 'light' {
		return _theme;
	},

	/** Call once from the root layout onMount to read saved preference. */
	init(): void {
		if (typeof window === 'undefined') return;
		let raw: string | null = null;
		try { raw = localStorage.getItem('veent-theme'); } catch (_) {}
		const saved: 'dark' | 'light' | null = raw === 'dark' || raw === 'light' ? raw : null;
		const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
		const resolved: 'dark' | 'light' = saved ?? (prefersDark ? 'dark' : 'light');
		_theme = resolved;
		applyClass(resolved);
	},

	toggle(): void {
		const next: 'dark' | 'light' = _theme === 'dark' ? 'light' : 'dark';
		// Brief transition class so colors animate smoothly only during the toggle.
		document.documentElement.classList.add('theme-transitioning');
		_theme = next;
		applyClass(next);
		localStorage.setItem('veent-theme', next);
		setTimeout(() => document.documentElement.classList.remove('theme-transitioning'), 300);
	}
};

function applyClass(theme: 'dark' | 'light'): void {
	document.documentElement.classList.toggle('light', theme === 'light');
}
