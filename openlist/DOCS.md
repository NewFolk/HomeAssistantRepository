# OpenList add-on

[OpenList](https://github.com/OpenListTeam/OpenList) provides a single web interface for files stored by many different storage providers.

This add-on currently packages OpenList `v4.2.7`, supports `amd64`, and remains experimental until its Ingress behavior has been verified on a real Home Assistant installation.

## First start

1. Start the add-on and watch its log until OpenList is ready.
2. Select **Open Web UI** on the add-on page.
3. On a fresh OpenList 4.2.7 installation, complete the web setup wizard and choose the administrator username and a strong password. Keep `ingress_auto_login: false` until setup is complete. Existing installations keep their administrator account; older OpenList releases printed a generated initial password in the log.
4. Change any old generated/default administrator password immediately.
5. Add storage providers in the OpenList administration interface.

OpenList's database, configuration, and generated keys are stored in the add-on's persistent `/data` directory and survive restarts and upgrades.

The container exposes a native Docker health check for the web endpoint, and CI probes that endpoint during every build.

## Web interface

Use **Open Web UI** for access through Home Assistant Ingress. The add-on runs an internal proxy that adapts OpenList's frontend, API, and WebSocket URLs to Home Assistant's installation-specific Ingress path.

If direct access is enabled in the add-on's **Network** section, open `http://HOME_ASSISTANT_HOST:5244/openlist/`. Direct access uses OpenList authentication and should not be exposed to the internet without a trusted HTTPS reverse proxy. Prefer direct access for large uploads because Home Assistant Ingress may buffer upload requests.

### Optional administrator auto-login through Ingress

With **Supervisor 2026.10.2 or newer**, you can open OpenList as its existing administrator without entering an OpenList password. Add this top-level option in the add-on's **Configuration** tab, keeping your existing `openlist` settings:

```yaml
ingress_auto_login: true
openlist: {}
```

Complete OpenList's initial setup first. Save, restart the add-on, and select **Open Web UI** while signed in to Home Assistant as an administrator. The default is `ingress_auto_login: false`, which keeps normal OpenList login. Set it back to `false` and restart to disable auto-login. Do not replace a populated `openlist` mapping with `{}` unless you want to remove its overrides.

Security boundaries:

- Only Home Assistant administrators can use this admin-only Ingress panel. Supervisor 2026.10.2 introduced the required [server-side `panel_admin` enforcement](https://github.com/home-assistant/supervisor/pull/7308); hiding a menu entry on older versions was not sufficient. Startup fails with a log message if auto-login is requested but the minimum stable Supervisor version cannot be verified. Update Supervisor or disable the option to recover.
- The proxy accepts automatic credentials only on requests from Supervisor's internal IP with its authenticated user header. Missing identity, direct/spoofed requests and cross-origin browser requests are rejected. State-changing browser requests must provide a matching `Origin` header.
- The existing OpenList admin API token is read from SQLite in read-only mode and attached to the internal upstream request. Auto-login does not return a new login token/cookie to the browser, patch frontend JavaScript, reset passwords or change the database. Token rotation is picked up on the next request. OpenList's own administration pages can still expose secrets to administrators as usual.
- This intentionally bypasses OpenList's password and second factor **through Ingress only**. Protect your Home Assistant administrator accounts and use HA MFA. Everyone using this route shares the same OpenList administrator permissions; actions are not separated into individual OpenList accounts. Signing out inside OpenList does not revoke HA access: sign out of HA or disable this option.
- Port `5244/tcp` remains **unpublished by default**. If you explicitly publish it, it still uses normal OpenList authentication; HA headers do not grant access there. The feature does not enable guest access or create new filesystem mounts. Never expose the internal proxy/helper ports `8099`/`8098` directly.

The feature is covered by helper and real-container tests, but still requires validation on your Home Assistant installation, including an HA administrator, a non-admin account and logout behavior. Keep a backup before updating. No Home Assistant Core API access or Supervisor administrator role is granted to the add-on.

## OpenList settings in Home Assistant

Open the add-on's **Configuration** tab. It uses Home Assistant's built-in YAML editor. Put any settings documented for OpenList's [config.json](https://doc.oplist.org/configuration/configuration) under `openlist`, keeping the same names and nesting:

```yaml
openlist:
  tasks:
    copy:
      task_persistant: true
    move:
      task_persistant: true
    download:
      task_persistant: true
    transfer:
      task_persistant: true
    decompress:
      task_persistant: true
  log:
    max_age: 14
  token_expires_in: 168
```

Save and restart the add-on. Numbers and booleans retain their types; use `true`, not `"true"`. JSON syntax is also valid YAML. Only specify fields you want to override. Nested objects merge recursively, while arrays replace the entire original array. A parameter must be supported by the installed OpenList version; there is no add-on allowlist of general OpenList settings. OpenList can ignore unknown keys, so check spelling against its documentation.

`/data/config.json` remains the persistent source, including generated keys and any pre-existing manual configuration. The add-on builds a private working copy at `/data/.openlist-runtime.json` on each start. Removing a field from HA restores the source value (or the upstream default when the source has no value). Set `openlist: {}` to remove all HA overrides. Do not edit the generated working copy. OpenList configuration environment variables are ignored for the working copy, ensuring the YAML settings take effect.

The add-on owns `force`, `site_url`, `last_launched_version`, `scheme.address`, `scheme.http_port`, `scheme.https_port`, `scheme.force_https`, `scheme.unix_file`, `database.type`, and `database.db_file`. Do not specify these in overrides: they keep Ingress, health checks, and the persistent SQLite database working. An attempt to override them stops startup with the offending field name in the log. Root/section structure and JSON syntax are checked before launching. OpenList 4.2.7 has no standalone config-validation command; it validates its own field types during startup and reports errors in the log. Configuration values are not dumped by the wrapper.

On a fresh installation, the upstream `admin` command initializes the persistent source before the first working copy is built. In OpenList 4.2.7 the administrator is then created through the web setup wizard, not automatically by that command. Existing installations keep their source configuration and database. Paths outside `/data`, `/share`, and `/media` do not acquire persistent storage or extra host access by being specified here.

These overrides cover file-based OpenList configuration, not users, storage providers, or settings stored in its database. Continue managing those through the OpenList UI. Task persistence applies only to future tasks and only to task types supported upstream; ordinary upload and decompress-upload tasks do not support persistence in this version. Enabling persistence cannot recover an earlier in-memory task list.

## Home Assistant folders

The add-on can access these Home Assistant folders:

- `/share` with read/write access;
- `/media` with read-only access.

To expose a local folder through OpenList, configure a local storage provider and select a path under one of those locations.

## Direct network access

Home Assistant Ingress is enabled by default and does not require opening a port. If direct access is needed, set the host port for `5244/tcp` in the add-on's **Network** section and use the `/openlist/` path. Authentication and TLS must be configured appropriately before exposing OpenList outside a trusted network.

## Backup

Home Assistant add-on backups include `/data`. The add-on uses cold backups, so Home Assistant stops OpenList while taking a backup to keep its database consistent. Create a backup before upgrading the add-on or making significant storage configuration changes.

## Support

- Add-on packaging issues: [this repository's issue tracker](https://github.com/NewFolk/HomeAssistantRepository/issues)
- OpenList application issues: [OpenList issue tracker](https://github.com/OpenListTeam/OpenList/issues)
