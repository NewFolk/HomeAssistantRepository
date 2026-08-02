# Changelog

## 1.1.1

- Update OpenList from `v4.2.2` to `v4.2.4`.
- Derive CI release expectations from the add-on metadata and pinned image tag.
- Improve smoke-test diagnostics when an upstream version does not match.

## 1.1.0

- Pin OpenList to `v4.2.2` and its immutable container manifest digest.
- Limit the supported architecture to the CI-tested `amd64` build.
- Add a native container health check and CI HTTP probe.
- Add CI smoke and persistence tests.
- Start OpenList with its verified data-directory and no-prefix flags.
- Mark the add-on experimental until Ingress is verified on Home Assistant.

## 1.0.0

- Initial OpenList add-on release.
- Add Ingress and optional direct port access.
- Persist OpenList state in the Home Assistant add-on data directory.
- Mount Home Assistant's shared and media directories.
