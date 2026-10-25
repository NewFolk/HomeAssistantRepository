# OpenList

Unofficial Home Assistant add-on packaging for [OpenList](https://github.com/OpenListTeam/OpenList). The current experimental release packages OpenList `v4.2.9` for `amd64`.

See [the add-on documentation](DOCS.md) for installation, storage, networking, and backup guidance.

OpenList file-based settings can be supplied in the Home Assistant Configuration tab as a YAML text block starting with `openlist: |`. Keep that vertical bar: HA stores a string, which the add-on parses into native settings. See [configuration and migration guidance](DOCS.md#openlist-settings-in-home-assistant).

Startup verifies the supplied settings after OpenList reads them and logs accepted field paths without values. Misspelled/ignored fields and duplicate YAML keys stop startup with a diagnostic instead of silently doing nothing.

Optional `ingress_auto_login: true` signs Home Assistant administrators into the existing OpenList administrator account through Ingress. It requires Supervisor 2026.10.2+, is disabled by default, and does not enable the optional direct port or remove its normal authentication. See [security boundaries and setup](DOCS.md#optional-administrator-auto-login-through-ingress).

Ingress login is handled by HA/Supervisor following Home Assistant's standard model; the add-on does not require external-URL, Origin or Fetch Metadata settings.

The OpenList icon and logo are used under their separate license; see [NOTICE.md](NOTICE.md).
