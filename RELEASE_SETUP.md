# One-time public release setup

Most technical work is automated in this repository. The remaining steps require the owner's GitHub/PyPI account, agreement acceptance, and two-factor authentication.

## 1. Configure owner placeholders

From the repository root:

```powershell
py scripts/configure_release.py --owner YOUR_GITHUB_USERNAME
```

This replaces `abubakarfaisal804-wq` in README and issue metadata and adds project URLs to `pyproject.toml`.

## 2. Create and push the public repository

Fastest route with GitHub CLI already authenticated:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/publish_github.ps1 -Owner YOUR_GITHUB_USERNAME
```

The script initializes Git, creates a public repository named `e2eproof`, pushes `main`, and prints the next account-only steps. It never asks for or stores a GitHub token; `gh auth login` handles authentication.

## 3. Wait for CI

Do not publish a release while required workflows are red. The intended required checks are:

- Static analysis
- Unit matrix
- Full coverage with Chromium
- Build and clean-install package
- 9-job browser matrix
- Action self-test
- CodeQL
- Dependency review for pull requests

## 4. Configure PyPI Trusted Publishing

Create accounts on PyPI and TestPyPI. Add pending trusted publishers with:

- PyPI project name: `e2eproof`
- GitHub owner: your username or organization
- Repository: `e2eproof`
- Workflow: `release.yml` for PyPI
- Environment: `pypi`
- Workflow: `testpypi.yml` for TestPyPI
- Environment: `testpypi`

In GitHub repository settings, create environments named `pypi` and `testpypi`. Require manual approval for `pypi`.

## 5. Test TestPyPI

Run the `publish to TestPyPI` workflow manually. Then clean-install from TestPyPI in a disposable environment and run:

```bash
e2eproof --version
e2eproof quickstart --yes --no-open
```

## 6. Publish the Marketplace release

Open `action.yml` on GitHub and use the Marketplace banner to draft a release.

- Accept the Marketplace Developer Agreement when prompted.
- Check **Publish this Action to the GitHub Marketplace**.
- Primary category: Testing
- Secondary category: Security or Continuous integration
- Tag: `v0.2.0`
- Title: `E2EProof v0.2.0 — public alpha`
- Paste `RELEASE_NOTES_v0.2.0.md`.
- Publish with two-factor authentication.

The release workflow then builds, checks, attests, attaches distributions, and publishes to PyPI through Trusted Publishing.

## 7. Maintain action tags

After the release succeeds, create or move the stable major tag `v0` to the release commit for early alpha users. At the first stable release, use `v1`. Never move an immutable exact tag such as `v0.2.0`.
