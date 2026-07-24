# Security

## API credentials

Version 2.0 stores credentials through Python `keyring`, which delegates secret storage to the operating system. Workflow files should contain only a connection from the Credential Manager node, not a literal secret.

The extension stores a local `geekatplay_keystore.json` index containing credential names only. It is excluded from Git. Legacy `geekatplay_keystore.enc` files are migrated automatically and renamed to `geekatplay_keystore.enc.migrated`.

Do not publish workflows containing API keys entered directly into service-node widgets. Prefer the Credential Manager or the `TRIPO_API_KEY` environment variable.

## Reporting a vulnerability

Please report security issues privately through GitHub's security-advisory feature for this repository. Do not open a public issue containing API keys, tokens, or exploit details.
