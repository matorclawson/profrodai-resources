# Lucy’s shop Codespace

The configuration uses Python 3.12 and the committed `uv.lock`. Creation runs a locked installation; it does not make a model call.

For command-line qualification, the OpenSSH feature is pinned to `ghcr.io/devcontainers/features/sshd:1.1.0`. It installs the OpenSSH server/client and lsof, creates an SSH group, adjusts PAM, and sets `PermitRootLogin yes`. Its entrypoint starts the server on port 2222. This port is not forwarded and the feature creates no default password; command-line access uses `gh codespace ssh`.
