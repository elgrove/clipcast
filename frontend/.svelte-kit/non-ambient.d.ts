
// this file is generated — do not edit it


declare module "svelte/elements" {
	export interface HTMLAttributes<T> {
		'data-sveltekit-keepfocus'?: true | '' | 'off' | undefined | null;
		'data-sveltekit-noscroll'?: true | '' | 'off' | undefined | null;
		'data-sveltekit-preload-code'?:
			| true
			| ''
			| 'eager'
			| 'viewport'
			| 'hover'
			| 'tap'
			| 'off'
			| undefined
			| null;
		'data-sveltekit-preload-data'?: true | '' | 'hover' | 'tap' | 'off' | undefined | null;
		'data-sveltekit-reload'?: true | '' | 'off' | undefined | null;
		'data-sveltekit-replacestate'?: true | '' | 'off' | undefined | null;
	}
}

export {};


declare module "$app/types" {
	type MatcherParam<M> = M extends (param : string) => param is (infer U extends string) ? U : string;

	export interface AppTypes {
		RouteId(): "/" | "/admin" | "/admin/config" | "/admin/reports" | "/podcast" | "/podcast/add" | "/podcast/[id]";
		RouteParams(): {
			"/podcast/[id]": { id: string }
		};
		LayoutParams(): {
			"/": { id?: string };
			"/admin": Record<string, never>;
			"/admin/config": Record<string, never>;
			"/admin/reports": Record<string, never>;
			"/podcast": { id?: string };
			"/podcast/add": Record<string, never>;
			"/podcast/[id]": { id: string }
		};
		Pathname(): "/" | "/admin/config" | "/admin/reports" | "/podcast/add" | `/podcast/${string}` & {};
		ResolvedPathname(): `${"" | `/${string}`}${ReturnType<AppTypes['Pathname']>}`;
		Asset(): string & {};
	}
}