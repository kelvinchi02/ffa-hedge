# ffa-hedge
Real-time FFA basis streaming and robust hedging optimization using CVXPY

## CI/CD

This repository now includes a GitHub Actions pipeline at `.github/workflows/ci-cd.yml`.

- CI runs on pull requests to `main` and pushes to `main`.
- CI validates the project by running `pytest` on Python 3.10, 3.11, and 3.12.
- CD runs when a tag starting with `v` is pushed (for example `v1.0.0`).
- CD creates a zip release bundle and publishes it as a GitHub Release asset.

### Trigger a release

```bash
git tag v1.0.0
git push origin v1.0.0
```
