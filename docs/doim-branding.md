# DOIM branding configuration

`config/branding.toml` is the single public configuration source for the static site's
name, official link, disclaimer, theme, optional assets, and analytics choice. Publish a
change with:

```bash
uv run doim-branding
```

The command writes `data/branding.json` and an identical `site/data/branding.json`.
The browser reads that small document before it reads the faculty directory, applies the
CSS theme variables, and updates the title, official links, disclaimer, and social-card
metadata.

## Assets and marks

Asset values are simple filenames resolved only inside `site/assets/`; remote URLs and
path traversal are rejected. `doim-explorer-social-card.png` is an editorial social
card, not a University logo or mark. `assets.mark` is intentionally blank.

Do not add a University of Utah logo, seal, Block U, or other trademarked mark merely to
make the site look official. This is an unofficial explorer. Add an approved local mark
only after the relevant University approval has been obtained, then set `assets.mark` to
its filename. The University’s [web requirements](https://regulations.utah.edu/it/rules/Rule4-003G.php)
describe the approval boundary for non-institutional sites; the default Utah-red palette
comes from the [University brand color guide](https://brand.utah.edu/wp-content/uploads/sites/69/2023/10/university-of-utah-brand-colors-toolkit.pdf).

## Analytics

Analytics is opt-in. Leave `analytics.measurement_id` blank to load no analytics code.
When an authorized project owner chooses to enable Google Analytics, set a public GA4
measurement ID in the form `G-XXXXXXXX`; the browser then loads `gtag.js`. A measurement
ID is not a secret, so do not put credentials or API keys in this file or in the static
site.
