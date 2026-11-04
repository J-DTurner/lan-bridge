# Public source and private device data

The public repository contains generic source and build/setup instructions. Machine
configuration, IP addresses, device certificates/fingerprints, pairing exports,
clipboard/files, logs and diagnostic reports stay on the owner's devices.
Private handoff ZIPs and Git bundles must not be uploaded as release assets.

The initial public branch is a **new sanitized snapshot**. Private development
history is not pushed, even if the current worktree is clean. Commit authors and
committers use the project identity with a neutral local email, and UTC timestamps.
Third-party copyright/license attribution is retained.

## Audit

```sh
python scripts/audit-public.py --require-snapshot
```

This checks every reachable commit's metadata and file blobs, including retired
file versions. It rejects machine IP literals, MAC/fingerprint literals, certificates,
private keys, common token patterns, personal email/user-home literals, runtime data,
archives and binary payloads. Unspecified/loopback bind addresses are generic code
constants, not device identifiers, and are allowed. The audit reports categories and
file paths rather than the matched secret values.

For owner-specific names/addresses, keep an additional JSON rule file **outside the
repository** with `forbidden_literals` set to a list of private strings. Pass its path
with `--private-rules`. Do not commit that file. Pattern scanning supplements the
manual review; it cannot recognize every possible personal detail automatically.

## First publication

Use a separate repository initialized from the reviewed source only. Do not run the
publisher from the private development checkout or copy that checkout's `.git` folder.
Create the first commit with the project author/committer identity, then run:

```sh
python scripts/publish-github.py --owner YOUR_GITHUB_LOGIN --check-only
python scripts/publish-github.py --owner YOUR_GITHUB_LOGIN
```

The publisher checks the snapshot again before any upload, uses the native `gh`
sign-in, checks the account matches the requested owner, creates a new **public**
`lan-bridge` repository, and pushes only the explicit `main` branch. Initial sign-in
may require browser interaction; never paste a token into chat or source files.
The workflow permission is needed to publish the included CI configuration.

It refuses to change an existing private repository's visibility or overwrite a
repository with different history. An existing empty public repository can be used.
It verifies public visibility, the remote commit and every remote blob against the
audited local snapshot. The script contains no machine address or account constant;
the destination is provided at execution time.

For subsequent development, use the public checkout and keep new commit metadata
nonpersonal. Audit all reachable history before a normal explicit branch push.
Keep private pairing/handoff distributions separate from public source updates.
