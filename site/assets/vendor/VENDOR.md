# Vendored browser libraries

The site has no bundler and no package manager, and it deliberately loads no scripts from a
CDN. Third-party browser code is therefore committed here, pinned to an exact version, and
verified by `tests/test_vendored_assets.py` so the bytes cannot drift or be swapped silently.

## cytoscape.min.js

| | |
|---|---|
| Package | [`cytoscape`](https://www.npmjs.com/package/cytoscape) |
| Version | 3.34.3 |
| License | MIT (`cytoscape.LICENSE.txt`) |
| Build | `dist/cytoscape.min.js` — UMD, zero runtime dependencies |
| Source | `https://cdn.jsdelivr.net/npm/cytoscape@3.34.3/dist/cytoscape.min.js` |
| SHA-256 | `5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91` |

Cytoscape draws the collaboration network on the Network view. It was chosen over Sigma.js
because Sigma v3 publishes no UMD build and depends on `graphology`, which would require
introducing a bundler; Cytoscape ships one self-contained UMD file with no dependencies.

### Updating

```bash
curl -sL -o site/assets/vendor/cytoscape.min.js \
  https://cdn.jsdelivr.net/npm/cytoscape@<version>/dist/cytoscape.min.js
curl -sL -o site/assets/vendor/cytoscape.LICENSE.txt \
  https://cdn.jsdelivr.net/npm/cytoscape@<version>/LICENSE
shasum -a 256 site/assets/vendor/cytoscape.min.js
```

Update the version and hash in this file and in `tests/test_vendored_assets.py`, then run
`uv run --locked pytest tests/test_vendored_assets.py` and load the Network view to confirm
the graph still renders.
