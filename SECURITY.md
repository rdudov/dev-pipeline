# Security policy

Do not report vulnerabilities through a public issue. Use GitHub's private vulnerability reporting for this repository when available, or contact the repository owner privately through their GitHub profile.

Never commit Codex credentials, tokens, private prompts/task data, native session storage, lifecycle state, or target-repository content. This project stores only caller-selected lifecycle metadata, but paths, process IDs, and session identifiers may still be sensitive operational data.

The CLI launches an authenticated coding agent in a caller-selected repository. Callers are responsible for choosing an appropriate Codex sandbox and for isolating untrusted repositories and instructions.
