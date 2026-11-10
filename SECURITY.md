# Security

Please report vulnerabilities privately to the repository owner through GitHub's private vulnerability reporting when available. Session refresh tokens provide access to the account; protect the local configuration directory and log out when access is no longer needed.

The CLI discovers public Firebase configuration and client identification from Skippo's official My Boat web app at runtime. These values are published by Skippo and are distinct from your account password and refresh token. Firebase [describes its service API keys](https://firebase.google.com/docs/projects/api-keys) as public configuration when appropriately restricted; this project has not verified the provider's key restrictions.

An earlier public commit contained the web app's public Firebase configuration key and triggered a GitHub secret scanning alert. Current code discovers the value instead. That earlier commit remains in public history; removing the value from current code does not remove the historical alert or rotate Skippo's key.
