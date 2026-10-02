# Google Street View fixtures: written, not recorded

No Google key was used to make these files. They follow the shapes Google documents for the [Street View metadata endpoint](https://developers.google.com/maps/documentation/streetview/metadata) (`status` of `OK`, `ZERO_RESULTS` or `REQUEST_DENIED`; `pano_id`, `location.lat`, `location.lng`, `date`, `copyright`) and for its image endpoint.

- The panorama IDs (`CurioFixturePano01` to `05`) are made up.
- `image.jpg` is synthetic noise, the size of a real image.
- `placeholder.jpg` is small and grey, like the image Google sends where it has none.

`scripts/write_streetview_fixtures.py` writes this folder and its entries in `../index.json`. It drives the real provider, so the URLs here are the ones the provider builds. Run it again after changing how the provider asks.

`test_provider_contracts.py` checks the real answers' shape when a key is set in `CURIO_GOOGLE_MAPS_KEY`.
