# Toji desktop

The packaged desktop opens the same compiled, authenticated application as the
browser. Start Docker Desktop, then run `docker compose up -d` from the repository
root. The default backend is http://127.0.0.1:8080.

For development, use `npm ci --no-audit --no-fund` in this directory, then
`npm start`. Set TOJI_API_URL to a plain origin for another backend. Only HTTPS
or loopback HTTP is accepted. The endpoint must identify itself as
toji-orchestrator and report a version; an unrelated HTTP 200 is insufficient.

The shell does not launch or stop backends, register startup tasks, expose IPC,
load Node in the renderer, or load a preload bridge. Renderer sandboxing, context
isolation and web security are enabled. Permissions, downloads, webviews, foreign
navigation and unapproved external windows are denied. The repository's GitHub
HTTPS links are the only approved external targets.

Build an unpacked Windows application with `npm run pack`, or installers with
`npm run dist`. Builds are unsigned unless your release process supplies signing.
The project lockfile is committed; host node_modules and machine-specific paths
are not packaged. The old voice and overlay implementation is archived and is
not a supported runtime feature.

On Google Drive, npm may fail writing dependencies. Build from a local disk copy
of this directory, preserving package.json and package-lock.json, then run the
same commands. The application itself still uses your configured backend.
