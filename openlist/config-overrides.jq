# Only the wrapper's top-level options are constrained; OpenList keys are open.
def options:
  if ($options | length) > 1 then error("HA options must contain a single JSON object") else . end
  |
  (if ($options | length) == 0 then {} else $options[0] end)
  | if type != "object" then error("HA options must be an object") else . end
  | if (keys - ["openlist"] | length) != 0 then
      error("Unknown HA option; put OpenList settings under openlist:") else . end
  | if has("openlist") then .openlist else {} end
  | if type != "object" then error("openlist must be an object, not a string/list/null") else . end;

def validate:
  . as $config
  | [
      ["force"], ["site_url"],
      ["scheme", "address"], ["scheme", "http_port"],
      ["scheme", "https_port"], ["scheme", "force_https"],
      ["scheme", "unix_file"], ["database", "type"], ["database", "db_file"]
    ] as $protected
  | if has("scheme") and (.scheme | type) != "object" then
      error("openlist.scheme must be an object") else . end
  | if has("database") and (.database | type) != "object" then
      error("openlist.database must be an object") else . end
  | reduce $protected[] as $path (.;
      if ($config | any(paths; . == $path)) then
        error("openlist." + ($path | join(".")) + " is managed by the HA add-on; remove this override")
      else . end);

(options | validate) as $overrides
| if type != "object" then error("Base OpenList configuration must be an object") else . end
| . * $overrides
| . * {
    force: true,
    site_url: "/openlist",
    scheme: {address: "0.0.0.0", http_port: 5244, https_port: -1, force_https: false, unix_file: ""},
    database: {type: "sqlite3", db_file: "/data/data.db"}
  }
