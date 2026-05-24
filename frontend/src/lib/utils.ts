export function formatDurationShort(seconds: number): string {
	const s = Math.max(0, Math.floor(seconds));
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const sec = s % 60;
	if (h > 0) {
		return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
	}
	return `${m}:${sec.toString().padStart(2, '0')}`;
}
