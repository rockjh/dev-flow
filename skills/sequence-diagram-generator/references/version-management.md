# Version and ownership

The only project baseline is `docs/sequence-diagram/sequence-diagram-generator-version.json`. Init preserves a valid existing baseline and rejects incompatible Skill versions. It is not an operation lock; core locks live externally and use the OS lock for the normalized project/domain key.

Accept rechecks sources, verification and the whole parent-baseline digest under the project-domain lock. Only registered generated assets with unchanged hashes may be replaced/deleted. Unregistered files, edited assets, case collisions, reserved Windows names and path escapes stop. Two prepared runs cannot both advance the same parent baseline.

The explicit run journal lists replacements, deletions, backups and written hashes. Multi-file commit is recoverable, not a single atomic operation. An interrupted accept stays verified; explicit accept retry first recovers only when current assets and baseline still match that transaction. Manual/newer changes prevent rollback. A finalized journal may complete the accepted manifest without reapplying assets. Accepted retry returns its recorded results without overwriting a newer revision.

Preserve accepted evidence and failed diagnostics. Clean only explicitly enumerated temporary files under the run's tmp directory. Never recursively delete user paths or other domain assets. Updating sources, parser implementations or semantic results needs a new run rather than editing frozen JSON.
