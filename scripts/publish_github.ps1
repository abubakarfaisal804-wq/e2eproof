param(
    [Parameter(Mandatory = $true)]
    [string]$Owner,

    [string]$Repository = "e2eproof"
)

$ErrorActionPreference = "Stop"

# Ga automatisch naar de hoofdmap van het project.
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

# Controleer invoer.
if ([string]::IsNullOrWhiteSpace($Owner) -or $Owner -eq "JOUW_GITHUB_NAAM") {
    throw "Voer een geldige GitHub-gebruikersnaam in."
}

if ($Owner -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,38}$') {
    throw "Ongeldige GitHub-gebruikersnaam: $Owner"
}

if ($Repository -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Ongeldige repositorynaam: $Repository"
}

Write-Host ""
Write-Host "E2EProof publiceren naar GitHub..." -ForegroundColor Cyan
Write-Host ""

# Controleer Git.
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is niet geïnstalleerd."
}

# Controleer GitHub CLI.
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI is niet geïnstalleerd."
}

# Controleer Python.
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
}
else {
    throw "Python is niet geïnstalleerd of niet toegevoegd aan PATH."
}

# Controleer GitHub-login zonder het script te laten stoppen.
Write-Host "GitHub-authenticatie controleren..."

cmd /c "gh auth status >nul 2>nul"
$authenticated = ($LASTEXITCODE -eq 0)

if (-not $authenticated) {
    Write-Host "GitHub-login openen..." -ForegroundColor Yellow

    gh auth login --web --git-protocol https

    if ($LASTEXITCODE -ne 0) {
        throw "Inloggen bij GitHub is mislukt."
    }
}

# Haal het actieve GitHub-account op.
[string]$githubLogin = gh api user --jq ".login"

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($githubLogin)) {
    throw "Het actieve GitHub-account kon niet worden opgehaald."
}

$githubLogin = $githubLogin.Trim()

Write-Host "Ingelogd als: $githubLogin" -ForegroundColor Green

if ($Owner -ne $githubLogin) {
    Write-Warning "Je bent ingelogd als '$githubLogin', maar publiceert naar '$Owner'."
}

# Configureer alle OWNER-velden en repositorylinks.
Write-Host "Releasebestanden configureren..."

& $pythonCommand "scripts/configure_release.py" --owner $Owner

if ($LASTEXITCODE -ne 0) {
    throw "Het configureren van de releasebestanden is mislukt."
}

# Initialiseer Git wanneer dit nog niet gebeurd is.
if (-not (Test-Path ".git" -PathType Container)) {
    Write-Host "Git-repository initialiseren..."

    git init -b main

    if ($LASTEXITCODE -ne 0) {
        throw "Git kon niet worden geïnitialiseerd."
    }
}
else {
    Write-Host "Bestaande Git-repository gevonden."

    git branch -M main

    if ($LASTEXITCODE -ne 0) {
        throw "De Git-branch kon niet naar 'main' worden gewijzigd."
    }
}

# Stel lokaal een Git-naam in wanneer die ontbreekt.
[string]$gitUserName = git config --get user.name

if ([string]::IsNullOrWhiteSpace($gitUserName)) {
    git config user.name $githubLogin

    if ($LASTEXITCODE -ne 0) {
        throw "De Git-gebruikersnaam kon niet worden ingesteld."
    }
}

# Stel lokaal een veilig GitHub noreply-adres in wanneer e-mail ontbreekt.
[string]$gitUserEmail = git config --get user.email

if ([string]::IsNullOrWhiteSpace($gitUserEmail)) {
    [string]$githubUserId = gh api user --jq ".id"

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($githubUserId)) {
        throw "Het GitHub-gebruikers-ID kon niet worden opgehaald."
    }

    $githubUserId = $githubUserId.Trim()
    $noreplyEmail = "$githubUserId+$githubLogin@users.noreply.github.com"

    git config user.email $noreplyEmail

    if ($LASTEXITCODE -ne 0) {
        throw "Het Git-e-mailadres kon niet worden ingesteld."
    }
}

# Voeg alle bestanden toe.
Write-Host "Bestanden aan Git toevoegen..."

git add --all

if ($LASTEXITCODE -ne 0) {
    throw "Bestanden toevoegen aan Git is mislukt."
}

# Maak alleen een commit wanneer er wijzigingen zijn.
$pendingChanges = git status --porcelain

if ($pendingChanges) {
    Write-Host "Eerste commit maken..."

    git commit -m "Prepare E2EProof public alpha v0.2.0"

    if ($LASTEXITCODE -ne 0) {
        throw "De Git-commit is mislukt."
    }
}
else {
    Write-Host "Geen nieuwe wijzigingen om te committen."
}

$fullName = "$Owner/$Repository"
$repositoryUrl = "https://github.com/$fullName"
$remoteUrl = "$repositoryUrl.git"

# Controleer veilig of de repository al bestaat.
cmd /c "gh repo view $fullName >nul 2>nul"
$repositoryExists = ($LASTEXITCODE -eq 0)

if ($repositoryExists) {
    Write-Host "Repository bestaat al: $repositoryUrl" -ForegroundColor Yellow
}
else {
    Write-Host "Openbare GitHub-repository aanmaken..."

    gh repo create $fullName `
        --public `
        --description "Deterministic browser-to-backend outcome verification with tamper-evident evidence"

    if ($LASTEXITCODE -ne 0) {
        throw "De GitHub-repository kon niet worden aangemaakt."
    }

    Write-Host "Repository aangemaakt." -ForegroundColor Green
}

# Voeg origin toe of corrigeer de bestaande origin.
$gitRemotes = @(git remote)

if ($gitRemotes -contains "origin") {
    git remote set-url origin $remoteUrl

    if ($LASTEXITCODE -ne 0) {
        throw "De bestaande origin-remote kon niet worden aangepast."
    }
}
else {
    git remote add origin $remoteUrl

    if ($LASTEXITCODE -ne 0) {
        throw "De origin-remote kon niet worden toegevoegd."
    }
}

# Push de volledige broncode.
Write-Host "Broncode naar GitHub pushen..."

git push -u origin main

if ($LASTEXITCODE -ne 0) {
    throw "Pushen naar GitHub is mislukt."
}

Write-Host "Broncode succesvol gepusht." -ForegroundColor Green

# Repository-instellingen en topics.
Write-Host "Repository-instellingen toepassen..."

cmd /c "gh repo edit $fullName --enable-issues --enable-wiki=false --add-topic e2e-testing --add-topic playwright --add-topic ai-testing --add-topic verification --add-topic github-actions >nul 2>nul"

if ($LASTEXITCODE -ne 0) {
    Write-Warning "Niet alle repositorytopics of instellingen konden worden toegepast."
}

# Discussions inschakelen.
cmd /c "gh api -X PATCH repos/$fullName -F has_discussions=true >nul 2>nul"

if ($LASTEXITCODE -ne 0) {
    Write-Warning "GitHub Discussions kon niet automatisch worden ingeschakeld."
}

Write-Host ""
Write-Host "Repository succesvol gepubliceerd:" -ForegroundColor Green
Write-Host $repositoryUrl -ForegroundColor Cyan
Write-Host ""
Write-Host "Wacht totdat alle GitHub Actions groen zijn."
Write-Host "Volg daarna RELEASE_SETUP.md voor PyPI en Marketplace."