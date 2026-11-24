# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Open a private security advisory on GitHub or contact the maintainer directly.
Do not open a public issue for a vulnerability.

## Credentials

The Redmine API key is read from the `REDMINE_API_KEY` environment variable
first, from the OS keychain when the optional `keyring` dependency is installed,
and from `$CONFIG_DIR/.env` last. The `.env` file is created with mode `0600`
and its plaintext entry is removed when the key is moved to a keyring backend.
The key is never written to logs and never included in error messages. The local
SQLite database contains issue ids, subjects, descriptions and tracked time, but
no credentials.

Keep `.env`, `config.ini`, `data.db` and the log files out of version control;
they are listed in `.gitignore` for that reason.

If a key leaks, revoke it in Redmine under My account → API access key and
enter a new one in the application.
