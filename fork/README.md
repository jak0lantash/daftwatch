# DaftWatch

Swipe through daft.ie property searches: save, hide, thumbs-down an area, type, BER or agent,
share your saved homes. A fork of [AdWatch](https://github.com/jak0lantash/adwatch); everything
DaftWatch-specific is in this `fork/` folder:

- `sites/daft.py`: reads daft.ie result pages (the JSON embedded in each page). daft.ie
  rate-limits, so pages are fetched **on demand**: page 1 when you open the Market, the next
  page when you're down to your last few homes, at least 20 s apart.
- `config.json`: fields (type, beds, BER, floor area, price per m², area, agent...), card
  layout, price-per-m² comparison, distances from Ballincollig (`CENTRE_NAME/LAT/LNG` override).
- `static/fork.js`, `fork.css`: the BER badge.

Adding a search: set it up on daft.ie, copy the address, paste it with a name. daft.ie's widest
radius is 20 km. Optional refinements include max distance and "only west of Ballincollig".

Core updates: `scripts/sync-upstream.sh` (the **Core updates** workflow opens an issue when
there are some). Image: `ghcr.io/jak0lantash/daftwatch:sha-<commit>`, built by **Test and build**.
