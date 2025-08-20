# Per-User Workspaces

LightRAG now isolates data for each authenticated user by deriving the
workspace name from the user's username. Every request authenticated with a
JWT token is handled in a workspace matching the token's `sub` field. This
allows multiple users to share a LightRAG instance while keeping their data
separate.

If no authentication token is supplied, LightRAG falls back to the default
workspace defined by the `WORKSPACE` environment variable or the value passed
on the command line.

## File Locations

All storage backends and the document input directory are scoped to the
workspace. For example, documents uploaded by user `alice` are stored under:

```
<INPUT_DIR>/alice/
```

## Migration Notes

* The `--workspace` argument is no longer required for per-user isolation.
* Existing deployments using a single workspace continue to work; requests
  without authentication use the default workspace.
* Ensure that usernames contain only characters valid for filesystem paths
  (letters, numbers and underscores).
