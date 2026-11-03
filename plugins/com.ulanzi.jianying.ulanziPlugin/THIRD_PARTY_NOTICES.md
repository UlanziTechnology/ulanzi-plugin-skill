# Third-party components

- Ulanzi plugin-common-html, commit `79de0b0b087546e684afd23f97223f7a7bc392da`, copied into `plugin/libs`.
- Ulanzi `plugin-common-python`, upstream commit `27a3c809619dff29e44b995a91a6299d5dff6d00`, plus the local feedback/state protocol additions present in the user's SDK working tree at generation time. Copied into `plugin/libs/ulanzi_api` without modifying that SDK checkout.
- websocket-client 1.9.0 is vendored in `site-packages` for the Python SDK transport.

These files retain their upstream notices and metadata where supplied.
License copies are collected in the `licenses` directory.
