# OpenList add-on

[OpenList](https://github.com/OpenListTeam/OpenList) provides a single web interface for files stored by many different storage providers.

This add-on currently packages OpenList `v4.2.2`, supports `amd64`, and remains experimental until its Ingress behavior has been verified on a real Home Assistant installation.

## First start

1. Start the add-on and watch its log until OpenList is ready.
2. Select **Open Web UI** on the add-on page.
3. Sign in with the initial administrator credentials printed in the add-on log.
4. Change the administrator password immediately.
5. Add storage providers in the OpenList administration interface.

OpenList's database, configuration, and generated keys are stored in the add-on's persistent `/data` directory and survive restarts and upgrades.

The container exposes a native Docker health check for the web endpoint, and CI probes that endpoint during every build.

## Home Assistant folders

The add-on can access these Home Assistant folders:

- `/share` with read/write access;
- `/media` with read-only access.

To expose a local folder through OpenList, configure a local storage provider and select a path under one of those locations.

## Direct network access

Home Assistant Ingress is enabled by default and does not require opening a port. If direct access is needed, set the host port for `5244/tcp` in the add-on's **Network** section. Authentication and TLS must be configured appropriately before exposing OpenList outside a trusted network.

## Backup

Home Assistant add-on backups include `/data`. The add-on uses cold backups, so Home Assistant stops OpenList while taking a backup to keep its database consistent. Create a backup before upgrading the add-on or making significant storage configuration changes.

## Support

- Add-on packaging issues: [this repository's issue tracker](https://github.com/NewFolk/HomeAssistantRepository/issues)
- OpenList application issues: [OpenList issue tracker](https://github.com/OpenListTeam/OpenList/issues)
