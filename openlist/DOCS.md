# OpenList add-on

[OpenList](https://github.com/OpenListTeam/OpenList) provides a single web interface for files stored by many different storage providers.

This add-on currently packages OpenList `v4.2.8`, supports `amd64`, and remains experimental until its Ingress behavior has been verified on a real Home Assistant installation.

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
openlist: "{}"
```

Complete OpenList's initial setup first. Save, restart the add-on, and select **Open Web UI** while signed in to Home Assistant as an administrator. The default is `ingress_auto_login: false`, which keeps normal OpenList login. Set it back to `false` and restart to disable auto-login. Keep any existing `openlist` text block; replacing it with `"{}"` removes its overrides.

Security boundaries:

- Only Home Assistant administrators can use this admin-only Ingress panel. Supervisor 2026.10.2 introduced the required [server-side `panel_admin` enforcement](https://github.com/home-assistant/supervisor/pull/7308); hiding a menu entry on older versions was not sufficient. Startup fails with a log message if auto-login is requested but the minimum stable Supervisor version cannot be verified. Update Supervisor or disable the option to recover.
- The proxy follows [Home Assistant's standard Ingress model](https://contributors.home-assistant.io/apps/guides/ingress/): HA/Supervisor authenticates the browser session, and automatic OpenList credentials are accepted only for requests from Supervisor's actual internal IP with its authenticated user header. Missing identity and direct/spoofed requests are rejected. The add-on does not implement a separate browser-session or Origin/Fetch Metadata policy.
- The existing OpenList admin API token is read from SQLite in read-only mode and attached to the internal upstream request. Auto-login does not return a new login token/cookie to the browser, patch frontend JavaScript, reset passwords or change the database. Token rotation is picked up on the next request. OpenList's own administration pages can still expose secrets to administrators as usual.
- This intentionally bypasses OpenList's password and second factor **through Ingress only**. Protect your Home Assistant administrator accounts and use HA MFA. Everyone using this route shares the same OpenList administrator permissions; actions are not separated into individual OpenList accounts. Signing out inside OpenList does not disable auto-login. HA/Supervisor control the Ingress session lifetime and revocation; verify logout behavior on your installation. To turn off auto-login reliably, set the option to `false` and restart the add-on.
- Port `5244/tcp` remains **unpublished by default**. If you explicitly publish it, it still uses normal OpenList authentication; HA headers do not grant access there. The feature does not enable guest access or create new filesystem mounts. Never expose the internal proxy/helper ports `8099`/`8098` directly.

The feature is covered by helper and real-container tests, but still requires validation on your Home Assistant installation, including an HA administrator, a non-admin account and logout behavior. Keep a backup before updating. No Home Assistant Core API access or Supervisor administrator role is granted to the add-on.

HTTPS termination (for example, at a router or reverse proxy) does not require entering the external HA URL again or configuring browser headers in this add-on. Version 1.4.3 removes the additional Origin/Fetch Metadata checks introduced in earlier releases; a stripped Origin no longer rejects an already HA-authenticated request. Ingress session authentication and browser-session protection belong to HA/Supervisor, not a second authentication scheme in this add-on. Keep Home Assistant updated and never expose or forward internal proxy/helper ports outside that boundary. We do not request Core API permission or read HA's Internet URL.

Startup explicitly logs whether auto-login is enabled or disabled. `untrusted_peer_or_missing_identity` means the adapter did not receive a trusted Supervisor request with a user identity. Older `missing_origin`, `origin_mismatch` and `cross_origin_fetch` errors came from the policy removed in 1.4.3. When reporting a problem, share the version and relevant errors, not a full HAR, copied curl or request headers containing cookies, Authorization or Ingress URLs.

## OpenList settings in Home Assistant

Open the add-on's **Configuration** tab. `ingress_auto_login` is a regular boolean switch. For advanced OpenList settings, select **⋮ → Edit in YAML** in the options card and use a **text block** beginning with `openlist: |`. Inside that block, use any settings documented for OpenList's [config.json](https://doc.oplist.org/configuration/configuration), keeping their names and nesting:

```yaml
ingress_auto_login: false
openlist: |
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

The `|` is required for multiline YAML: HA stores the entire block as a string, and the add-on safely parses it on startup. A bare `openlist:` mapping or `openlist: {}` is not supported by HA's schema; use the block above or a quoted JSON string, for example `openlist: '{"token_expires_in":168}'`. To remove all overrides, use `openlist: "{}"` or an empty string.

Save and restart the add-on, then reopen Configuration to check the saved values. Numbers and booleans **inside the block** retain their types after parsing; use `true`, not `"true"`. Only specify fields you want to override. Nested objects merge recursively, while arrays replace the entire original array. A parameter must be supported by the installed OpenList version; there is no add-on allowlist of general OpenList settings. Invalid inner YAML, duplicate YAML keys or unsupported value types stop startup with a concise log error; configuration values are not printed.

### Checking that settings were accepted

The initial `HA OpenList YAML parsed; working configuration prepared (verification pending)` message only confirms parsing and merging. The add-on waits for OpenList to read and rewrite its typed working configuration, then checks **every path supplied in HA**, including nested fields and array entries, before starting Ingress. Unknown keys discarded by OpenList and values/types that did not survive the round trip fail startup.

For the seven settings in the example above, expect messages including:

```text
[INFO] Verified HA override after OpenList load: openlist.tasks.copy.task_persistant
[INFO] All 7 HA OpenList override paths verified; values omitted
```

With only the five persistence flags, the total is five. An empty block logs `No HA OpenList overrides configured`. Values (including passwords, tokens and paths) are intentionally not printed; verification means the resulting value and type matched what was supplied in HA.

For example, misspelling `task_persistant` as `task_persistent` produces:

```text
[ERROR] HA override not accepted by OpenList: openlist.tasks.copy.task_persistent (unknown or discarded field); check spelling, nesting and type
```

Correct or remove the reported setting in HA Configuration and restart; no reinstall or data deletion is needed. This verifies recognition and file-based values, not every setting's semantic usefulness, external service availability or task execution. Existing ignored typos that previously appeared harmless will now prevent startup until corrected.

### Upgrading from add-on 1.3.0 or 1.4.0

Those releases incorrectly used `schema: false` as if it enabled arbitrary HA options. Supervisor actually turns it into an empty schema and silently removes all submitted keys, including `ingress_auto_login`. Saving can appear successful and suggest a restart, while the editor returns to defaults even when the add-on is stopped. This was an add-on packaging bug, not an OpenList restart problem.

Update to **1.4.1 or newer**, refresh the add-on page, and enter the desired settings again using the new text-block format. Previously discarded HA values cannot be recovered automatically. Do not reinstall the add-on or delete its data: the fix preserves the existing `/data/config.json`, database, users and storage providers. Settings that were never retained/applied cannot retroactively restore old in-memory task history.

`/data/config.json` remains the persistent source, including generated keys and any pre-existing manual configuration. The add-on builds a private working copy at `/data/.openlist-runtime.json` on each start. Removing a field from the text block restores the source value (or the upstream default when the source has no value). Set `openlist: "{}"` to remove all HA overrides. Do not edit the generated working copy. The add-on only reads `/data/options.json`; it never rewrites the options owned by Supervisor. OpenList configuration environment variables are ignored for the working copy, ensuring the YAML settings take effect.

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
