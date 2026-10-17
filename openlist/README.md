# OpenList

Unofficial Home Assistant add-on packaging for [OpenList](https://github.com/OpenListTeam/OpenList). The current experimental release packages OpenList `v4.2.7` for `amd64`.

See [the add-on documentation](DOCS.md) for installation, storage, networking, and backup guidance.

OpenList file-based settings can be supplied through the add-on's Home Assistant Configuration tab as nested YAML under `openlist`.

Optional `ingress_auto_login: true` signs Home Assistant administrators into the existing OpenList administrator account through Ingress. It requires Supervisor 2026.10.2+, is disabled by default, and does not enable the optional direct port or remove its normal authentication. See [security boundaries and setup](DOCS.md#optional-administrator-auto-login-through-ingress).

The OpenList icon and logo are used under their separate license; see [NOTICE.md](NOTICE.md).
