export const manifest = (() => {
function __memo(fn) {
	let value;
	return () => value ??= (value = fn());
}

return {
	appDir: "_app",
	appPath: "_app",
	assets: new Set([]),
	mimeTypes: {},
	_: {
		client: {start:"_app/immutable/entry/start.7USWOrmU.js",app:"_app/immutable/entry/app.QwBEf4z-.js",imports:["_app/immutable/entry/start.7USWOrmU.js","_app/immutable/chunks/BE5kQK6B.js","_app/immutable/chunks/D4KKLjDZ.js","_app/immutable/chunks/BUIKc9mW.js","_app/immutable/chunks/Cl-HN1rH.js","_app/immutable/entry/app.QwBEf4z-.js","_app/immutable/chunks/D4KKLjDZ.js","_app/immutable/chunks/C594jJnF.js","_app/immutable/chunks/Cl-HN1rH.js","_app/immutable/chunks/C9uwO1vK.js"],stylesheets:[],fonts:[],uses_env_dynamic_public:false},
		nodes: [
			__memo(() => import('./nodes/0.js')),
			__memo(() => import('./nodes/1.js')),
			__memo(() => import('./nodes/2.js')),
			__memo(() => import('./nodes/3.js')),
			__memo(() => import('./nodes/4.js')),
			__memo(() => import('./nodes/5.js')),
			__memo(() => import('./nodes/6.js'))
		],
		remotes: {
			
		},
		routes: [
			{
				id: "/",
				pattern: /^\/$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 2 },
				endpoint: null
			},
			{
				id: "/admin/config",
				pattern: /^\/admin\/config\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 3 },
				endpoint: null
			},
			{
				id: "/admin/reports",
				pattern: /^\/admin\/reports\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 4 },
				endpoint: null
			},
			{
				id: "/podcast/add",
				pattern: /^\/podcast\/add\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 6 },
				endpoint: null
			},
			{
				id: "/podcast/[id]",
				pattern: /^\/podcast\/([^/]+?)\/?$/,
				params: [{"name":"id","optional":false,"rest":false,"chained":false}],
				page: { layouts: [0,], errors: [1,], leaf: 5 },
				endpoint: null
			}
		],
		prerendered_routes: new Set([]),
		matchers: async () => {
			
			return {  };
		},
		server_assets: {}
	}
}
})();
